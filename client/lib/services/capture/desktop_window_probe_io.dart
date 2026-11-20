import 'dart:io';

import 'desktop_window_parsers.dart';
import 'desktop_window_probe_base.dart';

DesktopWindowProbe createDesktopWindowProbe() => DesktopWindowProbeIo();

class DesktopWindowProbeIo implements DesktopWindowProbe {
  @override
  Future<DesktopWindowSample?> activeWindow() async {
    if (Platform.isLinux) return _linux();
    if (Platform.isWindows) return _windows();
    if (Platform.isMacOS) return _macos();
    return null;
  }

  Future<DesktopWindowSample?> _linux() async {
    final methods = <Future<DesktopWindowSample?> Function()>[
      _hyprland,
      _sway,
      _kde,
      _gnomeExtension,
    ];
    for (final method in methods) {
      try {
        final sample = await method();
        if (sample != null) return await _withProcessFallback(sample);
      } on Object {
        // Try the next compositor strategy.
      }
    }
    // Never guess from stale XWayland properties on Wayland: compositor APIs
    // (or the GNOME extension) are the authoritative source there.
    if (_isWayland) return null;

    // X11 fallback through X properties / xdotool.
    try {
      final sample = await _x11();
      if (sample != null) return await _withProcessFallback(sample);
    } on Object {
      // No active window API available.
    }
    return null;
  }

  bool get _isWayland {
    final session = (Platform.environment['XDG_SESSION_TYPE'] ?? '').toLowerCase();
    return session == 'wayland' ||
        (Platform.environment['WAYLAND_DISPLAY']?.isNotEmpty ?? false);
  }

  Future<DesktopWindowSample?> _hyprland() async {
    final output = await _output('hyprctl', ['activewindow', '-j']);
    return output == null ? null : parseHyprlandWindow(output);
  }

  Future<DesktopWindowSample?> _sway() async {
    final output = await _output('swaymsg', ['-t', 'get_tree']);
    return output == null ? null : parseSwayTree(output);
  }

  Future<DesktopWindowSample?> _kde() async {
    for (final command in ['qdbus6', 'qdbus', 'qdbus-qt6']) {
      final output = await _output(command, ['org.kde.KWin', '/KWin', 'queryWindowInfo']);
      if (output == null) continue;
      final sample = parseKdeWindowInfo(output);
      if (sample != null) return sample;
    }
    return null;
  }

  Future<DesktopWindowSample?> _gnomeExtension() async {
    final output = await _output('gdbus', [
      'call',
      '--session',
      '--dest',
      'org.vira.Link.WindowInfo',
      '--object-path',
      '/org/vira/Link/WindowInfo',
      '--method',
      'org.vira.Link.WindowInfo.GetActiveWindow',
    ]);
    return output == null ? null : parseGnomeExtensionWindow(output);
  }

  Future<DesktopWindowSample?> _x11() async {
    final root = await _output('xprop', ['-root', '_NET_ACTIVE_WINDOW']);
    var windowId = root == null ? null : parseX11ActiveWindowId(root);
    if (windowId == null) {
      windowId = await _output('xdotool', ['getactivewindow']);
      windowId = windowId?.trim();
    }
    if (windowId == null || windowId.isEmpty) return null;
    final properties = await _output('xprop', [
      '-id',
      windowId,
      'WM_CLASS',
      '_NET_WM_NAME',
      'WM_NAME',
      '_NET_WM_PID',
    ]);
    if (properties != null) {
      final sample = parseX11Properties(properties);
      if (sample != null) return sample;
    }
    final appId = await _output('xdotool', [
      'getactivewindow',
      'getwindowclassname',
    ]);
    final title = await _output('xdotool', ['getactivewindow', 'getwindowname']);
    final pid = int.tryParse(
      (await _output('xdotool', ['getactivewindow', 'getwindowpid'])) ?? '',
    );
    if ((appId == null || appId.trim().isEmpty) &&
        (title == null || title.trim().isEmpty)) {
      return null;
    }
    final id = (appId ?? '').trim();
    return DesktopWindowSample(
      appId: id,
      appName: id.isEmpty ? (title ?? 'Desktop app') : id,
      title: (title ?? '').trim(),
      pid: pid,
      method: 'x11-xdotool',
    );
  }

  Future<DesktopWindowSample?> _windows() async {
    final script = r'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class ViraWin {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$handle = [ViraWin]::GetForegroundWindow()
if ($handle -eq [IntPtr]::Zero) { return }
$builder = New-Object System.Text.StringBuilder 512
[void][ViraWin]::GetWindowText($handle, $builder, 512)
$processId = 0
[void][ViraWin]::GetWindowThreadProcessId($handle, [ref]$processId)
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
@{ app = $process.ProcessName; pid = $processId; title = $builder.ToString() } | ConvertTo-Json -Compress
''';
    for (final command in ['powershell.exe', 'powershell', 'pwsh']) {
      final output = await _output(command, [
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        script,
      ]);
      if (output == null) continue;
      final sample = parseWindowsWindow(output);
      if (sample != null) return sample;
    }
    return null;
  }

  Future<DesktopWindowSample?> _macos() async {
    const script = '''
tell application "System Events"
  set frontApp to first application process whose frontmost is true
  set appName to name of frontApp
  set appPid to unix id of frontApp
  set appId to ""
  try
    set appId to bundle identifier of frontApp
  end try
  set winTitle to ""
  try
    set winTitle to name of front window of frontApp
  end try
  return appName & linefeed & appId & linefeed & appPid & linefeed & winTitle
end tell
''';
    final output = await _output('osascript', ['-e', script]);
    if (output != null) {
      final sample = parseMacOsWindow(output);
      if (sample != null) return sample;
    }
    // Fallback that does not require Automation permission for the app name.
    final front = await _output('lsappinfo', ['front']);
    if (front == null || front.trim().isEmpty) return null;
    final info = await _output('lsappinfo', [
      'info',
      '-only',
      'name',
      front.trim(),
    ]);
    if (info == null) return null;
    final match = RegExp(r'"LSDisplayName"\s*=\s*"([^"]+)"').firstMatch(info);
    final name = match?.group(1)?.trim() ?? front.trim();
    return DesktopWindowSample(
      appId: name,
      appName: name,
      title: '',
      pid: null,
      method: 'macos-lsappinfo',
    );
  }

  Future<DesktopWindowSample?> _withProcessFallback(
    DesktopWindowSample sample,
  ) async {
    if (sample.appId.isNotEmpty || sample.pid == null) return sample;
    final processName = await _processName(sample.pid!);
    if (processName == null || processName.isEmpty) return sample;
    return DesktopWindowSample(
      appId: processName,
      appName: processName,
      title: sample.title,
      pid: sample.pid,
      method: sample.method,
    );
  }

  Future<String?> _processName(int pid) async {
    try {
      final comm = await File('/proc/$pid/comm').readAsString();
      final name = comm.trim();
      if (name.isNotEmpty) return name;
    } on Object {
      // Fall back to ps.
    }
    final output = await _output('ps', ['-p', '$pid', '-o', 'comm=']);
    final name = output?.trim();
    return name == null || name.isEmpty ? null : name;
  }

  Future<String?> _output(
    String executable,
    List<String> arguments, {
    Duration timeout = const Duration(seconds: 4),
  }) async {
    try {
      final result = await Process.run(
        executable,
        arguments,
      ).timeout(timeout);
      if (result.exitCode != 0) return null;
      final text = result.stdout?.toString().trim() ?? '';
      return text.isEmpty ? null : text;
    } on Object {
      return null;
    }
  }
}
