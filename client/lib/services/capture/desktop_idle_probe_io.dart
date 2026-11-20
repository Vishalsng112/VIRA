import 'dart:io';

import 'desktop_idle_probe_base.dart';

DesktopIdleProbe createDesktopIdleProbe() => DesktopIdleProbeIo();

class DesktopIdleProbeIo implements DesktopIdleProbe {
  @override
  Future<int?> idleSeconds() async {
    if (Platform.isLinux) return _linux();
    if (Platform.isWindows) return _windows();
    if (Platform.isMacOS) return _macos();
    return null;
  }

  Future<int?> _linux() async {
    final gnome = await _output('gdbus', [
      'call',
      '--session',
      '--dest',
      'org.gnome.Mutter.IdleMonitor',
      '--object-path',
      '/org/gnome/Mutter/IdleMonitor/Core',
      '--method',
      'org.gnome.Mutter.IdleMonitor.GetIdletime',
    ]);
    if (gnome != null) {
      final match = RegExp(r'(\d+)').firstMatch(gnome);
      final millis = match == null ? null : int.tryParse(match.group(1)!);
      if (millis != null) return millis ~/ 1000;
    }
    final xprintidle = await _output('xprintidle', const []);
    if (xprintidle != null) {
      final millis = int.tryParse(xprintidle.replaceAll(RegExp(r'\D'), ''));
      if (millis != null) return millis ~/ 1000;
    }
    for (final command in ['qdbus6', 'qdbus', 'qdbus-qt6']) {
      final value = await _output(command, [
        'org.kde.screensaver',
        '/ScreenSaver',
        'org.freedesktop.ScreenSaver.GetSessionIdleTime',
      ]);
      final seconds = value == null
          ? null
          : int.tryParse(value.replaceAll(RegExp(r'\D'), ''));
      if (seconds != null) return seconds;
    }
    return null;
  }

  Future<int?> _windows() async {
    const script = r'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ViraIdle {
  [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
}
"@
$info = New-Object ViraIdle+LASTINPUTINFO
$info.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($info)
[void][ViraIdle]::GetLastInputInfo([ref]$info)
[Console]::WriteLine(([Environment]::TickCount - $info.dwTime))
''';
    for (final command in ['powershell.exe', 'powershell', 'pwsh']) {
      final output = await _output(command, [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        script,
      ]);
      final millis = output == null
          ? null
          : int.tryParse(output.replaceAll(RegExp(r'\D'), ''));
      if (millis != null) return millis ~/ 1000;
    }
    return null;
  }

  Future<int?> _macos() async {
    final output = await _output('ioreg', ['-c', 'IOHIDSystem']);
    if (output == null) return null;
    final match = RegExp(r'"HIDIdleTime"\s*=\s*(\d+)').firstMatch(output);
    final nanos = match == null ? null : int.tryParse(match.group(1)!);
    return nanos == null ? null : nanos ~/ 1000000000;
  }

  Future<String?> _output(
    String executable,
    List<String> arguments, {
    Duration timeout = const Duration(seconds: 4),
  }) async {
    try {
      final result = await Process.run(executable, arguments).timeout(timeout);
      if (result.exitCode != 0) return null;
      final text = result.stdout?.toString().trim() ?? '';
      return text.isEmpty ? null : text;
    } on Object {
      return null;
    }
  }
}
