import 'dart:convert';

import 'desktop_window_probe_base.dart';

String _humanize(String value) {
  final cleaned = value
      .replaceAll(RegExp(r'\.desktop$'), '')
      .replaceAll(RegExp(r'[_\-]+'), ' ')
      .trim();
  if (cleaned.isEmpty) return 'Desktop app';
  return cleaned
      .split(' ')
      .where((part) => part.isNotEmpty)
      .map((part) => part[0].toUpperCase() + part.substring(1))
      .join(' ');
}

Map<String, dynamic>? _jsonObject(String output) {
  final start = output.indexOf('{');
  final end = output.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try {
    final decoded = jsonDecode(output.substring(start, end + 1));
    return decoded is Map ? Map<String, dynamic>.from(decoded) : null;
  } on FormatException {
    return null;
  }
}

DesktopWindowSample? parseHyprlandWindow(String output) {
  final json = _jsonObject(output);
  if (json == null) return null;
  final appId = (json['class'] ?? json['initialClass'] ?? '').toString().trim();
  final title = (json['title'] ?? '').toString().trim();
  if (appId.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: appId,
    appName: _humanize(appId.isEmpty ? title : appId),
    title: title,
    pid: (json['pid'] as num?)?.toInt(),
    method: 'hyprland',
  );
}

DesktopWindowSample? parseSwayTree(String output) {
  final json = _jsonObject(output);
  if (json == null) return null;

  Map<String, dynamic>? findFocused(Map<String, dynamic> node) {
    final focused = node['focused'] == true;
    final appId = node['app_id']?.toString().trim() ?? '';
    final props = node['window_properties'];
    final properties = props is Map ? Map<String, dynamic>.from(props) : null;
    final hasWindow = appId.isNotEmpty || properties != null;
    if (focused && hasWindow) return node;
    final nodes = node['nodes'];
    if (nodes is List) {
      for (final child in nodes.whereType<Map>()) {
        final found = findFocused(Map<String, dynamic>.from(child));
        if (found != null) return found;
      }
    }
    final floating = node['floating_nodes'];
    if (floating is List) {
      for (final child in floating.whereType<Map>()) {
        final found = findFocused(Map<String, dynamic>.from(child));
        if (found != null) return found;
      }
    }
    return null;
  }

  final focused = findFocused(json);
  if (focused == null) return null;
  final props = focused['window_properties'];
  final properties = props is Map ? Map<String, dynamic>.from(props) : const {};
  final appId =
      (focused['app_id'] ??
              properties['class'] ??
              properties['instance'] ??
              '')
          .toString()
          .trim();
  final title =
      (focused['name'] ?? properties['title'] ?? '').toString().trim();
  if (appId.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: appId,
    appName: _humanize(appId.isEmpty ? title : appId),
    title: title,
    pid: (focused['pid'] as num?)?.toInt(),
    method: 'sway',
  );
}

DesktopWindowSample? parseKdeWindowInfo(String output) {
  final values = <String, String>{};
  for (final line in output.split('\n')) {
    final match = RegExp(r'^\s*([A-Za-z]+)\s*[:=]\s*(.+?)\s*$').firstMatch(line);
    if (match != null) values[match.group(1)!.toLowerCase()] = match.group(2)!;
  }
  if (values.isEmpty) return null;
  final appId = _compact(values['resourceclass'] ?? values['resourcename']);
  final title = _compact(values['caption']);
  if (appId.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: appId,
    appName: _humanize(appId.isEmpty ? title : appId),
    title: title,
    pid: int.tryParse(_compact(values['pid'])),
    method: 'kde',
  );
}

DesktopWindowSample? parseGnomeExtensionWindow(String output) {
  final json = _jsonObject(output);
  if (json == null) return null;
  final appId = _compact(
    json['app_id'] ?? json['wm_class'] ?? json['class'] ?? json['app'],
  );
  final title = _compact(json['title']);
  if (appId.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: appId,
    appName: _humanize(appId.isEmpty ? title : appId),
    title: title,
    pid: (json['pid'] as num?)?.toInt(),
    method: 'gnome-extension',
  );
}

DesktopWindowSample? parseWindowsWindow(String output) {
  final json = _jsonObject(output);
  if (json == null) return null;
  final app = _compact(json['app'] ?? json['process']);
  final title = _compact(json['title']);
  if (app.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: app,
    appName: _humanize(app.isEmpty ? title : app),
    title: title,
    pid: (json['pid'] as num?)?.toInt(),
    method: 'windows-foreground',
  );
}

DesktopWindowSample? parseMacOsWindow(String output) {
  final lines = output
      .split('\n')
      .map((line) => line.trim())
      .toList();
  if (lines.isEmpty) return null;
  final appName = lines[0];
  final appId = lines.length > 1 ? lines[1] : '';
  final pid = lines.length > 2 ? int.tryParse(lines[2]) : null;
  final title = lines.length > 3 ? lines[3] : '';
  if (appName.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: appId == 'missing value' ? appName : appId,
    appName: _humanize(appName.isEmpty ? title : appName),
    title: title == 'missing value' ? '' : title,
    pid: pid,
    method: 'macos-frontmost',
  );
}

String? parseX11ActiveWindowId(String output) {
  final match = RegExp(r'(0x[0-9a-fA-F]+)').firstMatch(output);
  if (match == null || match.group(1) == '0x0') return null;
  return match.group(1);
}

DesktopWindowSample? parseX11Properties(String output) {
  final classMatch = RegExp(r'WM_CLASS\(STRING\)\s*=\s*(.+)').firstMatch(output);
  final classes = RegExp(r'"([^"]*)"')
      .allMatches(classMatch?.group(1) ?? '')
      .map((match) => match.group(1)!)
      .where((value) => value.isNotEmpty)
      .toList();
  final appId = classes.isEmpty ? '' : classes.last;
  String title = '';
  for (final key in ['_NET_WM_NAME', 'WM_NAME']) {
    final match = RegExp(
      '${RegExp.escape(key)}\\([^)]*\\)\\s*=\\s*"([^"]*)"',
    ).firstMatch(output);
    if (match != null && match.group(1)!.isNotEmpty) {
      title = match.group(1)!;
      break;
    }
  }
  final pidMatch = RegExp(r'_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)').firstMatch(
    output,
  );
  if (appId.isEmpty && title.isEmpty) return null;
  return DesktopWindowSample(
    appId: appId,
    appName: _humanize(appId.isEmpty ? title : appId),
    title: title,
    pid: pidMatch == null ? null : int.tryParse(pidMatch.group(1)!),
    method: 'x11-xprop',
  );
}

String _compact(Object? value) {
  final text = value?.toString().trim() ?? '';
  return text == 'missing value' ? '' : text;
}
