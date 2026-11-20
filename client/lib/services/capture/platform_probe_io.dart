import 'dart:convert';
import 'dart:io';

import '../../core/models/device_info.dart';
import 'platform_probe_base.dart';

PlatformProbe createPlatformProbe() => PlatformProbeIo();

class PlatformProbeIo implements PlatformProbe {
  @override
  Future<DeviceProfile> profile() async {
    final platform = _platformName();
    return DeviceProfile(
      platform: platform,
      deviceType: _deviceType(),
      osVersion: _clean(Platform.operatingSystemVersion),
      hostname: _clean(Platform.localHostname),
    );
  }

  @override
  Future<Map<String, dynamic>?> hardwareSnapshot() async {
    if (!Platform.isLinux) return null;
    try {
      final memory = await _memory();
      final cpu = await _cpu();
      final uptime = await _uptime();
      return {
        'cpu': cpu,
        'memory': memory,
        'uptime_seconds': ?uptime,
        'platform': Platform.operatingSystem,
        'logical_cores': Platform.numberOfProcessors,
      };
    } on Object {
      return null;
    }
  }

  @override
  Future<Map<String, dynamic>?> batterySnapshot() async {
    if (!Platform.isLinux) return null;
    try {
      final supplies = Directory('/sys/class/power_supply');
      if (!await supplies.exists()) return null;
      await for (final entity in supplies.list()) {
        final name = entity.path.split('/').last;
        if (!name.startsWith('BAT')) continue;
        final capacity = await _readInt('${entity.path}/capacity');
        if (capacity == null) continue;
        final status = await _readText('${entity.path}/status');
        final powerNow = await _readInt('${entity.path}/power_now');
        final energyNow = await _readInt('${entity.path}/energy_now');
        double? temperature;
        final temp = await _readInt('${entity.path}/temp');
        if (temp != null && temp > 0) temperature = temp / 10.0;
        return {
          'level_percent': capacity,
          'charging': status?.toLowerCase() == 'charging',
          'temperature_c': ?temperature,
          'plugged': status?.toLowerCase(),
          if (powerNow != null && energyNow != null && powerNow > 0)
            'minutes_remaining': (energyNow / powerNow * 60).round(),
        };
      }
    } on Object {
      return null;
    }
    return null;
  }

  @override
  Future<Map<String, dynamic>?> healthSnapshot() async {
    if (Platform.isWindows) return _windowsHealth();
    if (!Platform.isLinux && !Platform.isMacOS) return null;
    try {
      final result = <String, dynamic>{};
      final df = await Process.run('df', ['-k', '/']);
      if (df.exitCode == 0) {
        final lines = (df.stdout?.toString() ?? '').trim().split('\n');
        if (lines.length >= 2) {
          final parts = lines.last.trim().split(RegExp(r'\s+'));
          if (parts.length >= 4) {
            final totalKb = int.tryParse(parts[1]);
            final freeKb = int.tryParse(parts[3]);
            if (totalKb != null) result['storage_total_bytes'] = totalKb * 1024;
            if (freeKb != null) result['storage_free_bytes'] = freeKb * 1024;
          }
        }
      }
      if (Platform.isLinux) {
        final memory = await _memory();
        if (memory['total_bytes'] != null) {
          result['memory_total_bytes'] = memory['total_bytes'];
        }
        if (memory['available_bytes'] != null) {
          result['memory_available_bytes'] = memory['available_bytes'];
        }
        final thermal = await _thermal();
        if (thermal != null) result['thermal_c'] = thermal;
      }
      return result.isEmpty ? null : result;
    } on Object {
      return null;
    }
  }

  Future<double?> _thermal() async {
    try {
      final root = Directory('/sys/class/thermal');
      if (!await root.exists()) return null;
      double? hottest;
      await for (final entity in root.list()) {
        final name = entity.path.split('/').last;
        if (!name.startsWith('thermal_zone')) continue;
        final raw = await _readInt('${entity.path}/temp');
        if (raw == null) continue;
        var celsius = raw > 1000 ? raw / 1000.0 : raw.toDouble();
        if (celsius < -20 || celsius > 150) continue;
        if (hottest == null || celsius > hottest) hottest = celsius;
      }
      return hottest;
    } on Object {
      return null;
    }
  }

  Future<Map<String, dynamic>?> _windowsHealth() async {
    const script = r'''
$os = Get-CimInstance Win32_OperatingSystem
$drive = Get-PSDrive C
@{ storage_free_bytes = $drive.Free; storage_total_bytes = ($drive.Used + $drive.Free); memory_available_bytes = ($os.FreePhysicalMemory * 1024); memory_total_bytes = ($os.TotalVisibleMemorySize * 1024) } | ConvertTo-Json -Compress
''';
    for (final command in ['powershell.exe', 'powershell', 'pwsh']) {
      try {
        final result = await Process.run(command, [
          '-NoProfile',
          '-NonInteractive',
          '-Command',
          script,
        ]).timeout(const Duration(seconds: 8));
        if (result.exitCode != 0) continue;
        final text = result.stdout?.toString() ?? '';
        final start = text.indexOf('{');
        final end = text.lastIndexOf('}');
        if (start < 0 || end <= start) continue;
        final decoded = jsonDecode(text.substring(start, end + 1));
        if (decoded is Map) return Map<String, dynamic>.from(decoded);
      } on Object {
        continue;
      }
    }
    return null;
  }

  Future<int?> _readInt(String path) async {
    final text = await _readText(path);
    return text == null ? null : int.tryParse(text);
  }

  Future<String?> _readText(String path) async {
    try {
      return (await File(path).readAsString()).trim();
    } on Object {
      return null;
    }
  }

  @override
  Future<Map<String, dynamic>?> networkSnapshot() async {
    try {
      final interfaces = await NetworkInterface.list(
        includeLoopback: false,
        type: InternetAddressType.any,
      );
      final active = interfaces.where((item) => item.addresses.isNotEmpty);
      return {
        'interface_count': interfaces.length,
        'active_interface_count': active.length,
        'has_ipv4': active.any(
          (item) => item.addresses.any((a) => a.type == InternetAddressType.IPv4),
        ),
        'has_ipv6': active.any(
          (item) => item.addresses.any((a) => a.type == InternetAddressType.IPv6),
        ),
      };
    } on Object {
      return null;
    }
  }

  String _platformName() {
    if (Platform.isAndroid) return 'android';
    if (Platform.isIOS) return 'ios';
    if (Platform.isWindows) return 'windows';
    if (Platform.isMacOS) return 'macos';
    if (Platform.isLinux) return 'linux';
    return 'other';
  }

  String _deviceType() {
    if (Platform.isAndroid || Platform.isIOS) return 'phone';
    if (Platform.isLinux || Platform.isWindows || Platform.isMacOS) {
      return 'desktop';
    }
    return 'other';
  }

  String _clean(String value) {
    final text = value.replaceAll(RegExp(r'\s+'), ' ').trim();
    return text.length > 100 ? text.substring(0, 100) : text;
  }

  Future<Map<String, dynamic>> _memory() async {
    final text = await File('/proc/meminfo').readAsString();
    int? total;
    int? available;
    for (final line in text.split('\n')) {
      final match = RegExp(r'^(MemTotal|MemAvailable):\s+(\d+)').firstMatch(line);
      if (match == null) continue;
      final kb = int.parse(match.group(2)!);
      if (match.group(1) == 'MemTotal') total = kb;
      if (match.group(1) == 'MemAvailable') available = kb;
    }
    if (total == null) return const {};
    final used = total - (available ?? total);
    return {
      'total_bytes': total * 1024,
      'available_bytes': (available ?? total) * 1024,
      'usage_percent': total == 0 ? 0 : (used / total * 100).round(),
    };
  }

  Future<Map<String, dynamic>> _cpu() async {
    final first = await _cpuTimes();
    await Future<void>.delayed(const Duration(milliseconds: 200));
    final second = await _cpuTimes();
    final total = second.$1 - first.$1;
    final idle = second.$2 - first.$2;
    final usage = total <= 0 ? 0 : ((total - idle) / total * 100);
    return {'usage_percent': usage.round()};
  }

  Future<(int, int)> _cpuTimes() async {
    final text = await File('/proc/stat').readAsString();
    final line = text.split('\n').firstWhere(
      (item) => item.startsWith('cpu '),
      orElse: () => '',
    );
    final values = line
        .trim()
        .split(RegExp(r'\s+'))
        .skip(1)
        .map(int.tryParse)
        .whereType<int>()
        .toList();
    if (values.isEmpty) return (0, 0);
    final idle = values.length > 3
        ? values[3] + (values.length > 4 ? values[4] : 0)
        : values[0];
    return (values.fold<int>(0, (sum, value) => sum + value), idle);
  }

  Future<int?> _uptime() async {
    try {
      final text = await File('/proc/uptime').readAsString();
      final seconds = double.tryParse(text.split(' ').first);
      return seconds?.round();
    } on Object {
      return null;
    }
  }
}
