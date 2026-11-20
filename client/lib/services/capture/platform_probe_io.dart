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
