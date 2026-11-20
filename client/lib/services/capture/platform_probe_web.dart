import 'package:flutter/foundation.dart';

import '../../core/models/device_info.dart';
import 'platform_probe_base.dart';

PlatformProbe createPlatformProbe() => PlatformProbeWeb();

class PlatformProbeWeb implements PlatformProbe {
  @override
  Future<DeviceProfile> profile() async => DeviceProfile(
    platform: 'web',
    deviceType: 'browser',
    osVersion: defaultTargetPlatform.name,
    hostname: 'browser',
  );

  @override
  Future<Map<String, dynamic>?> hardwareSnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> networkSnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> batterySnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> healthSnapshot() async => null;
}
