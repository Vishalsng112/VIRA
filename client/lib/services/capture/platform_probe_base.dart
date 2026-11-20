import '../../core/models/device_info.dart';

/// Platform-specific probes used by capture collectors.
///
/// Implementations are selected at compile time, so web builds never import
/// `dart:io`. A collector can return `null` when the platform does not expose a
/// signal; the capture service then reports the capability as unavailable.
abstract class PlatformProbe {
  Future<DeviceProfile> profile();

  Future<Map<String, dynamic>?> hardwareSnapshot();

  Future<Map<String, dynamic>?> networkSnapshot();
}
