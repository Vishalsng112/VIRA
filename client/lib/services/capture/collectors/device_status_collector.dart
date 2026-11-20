import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/utils/ids.dart';
import '../collector.dart';
import '../platform_probe_base.dart';

/// Basic device/app identity. Works on every platform, including the web.
class DeviceStatusCollector implements Collector {
  @override
  String get id => collectorDeviceStatus;
  @override
  String get title => 'Device status';
  @override
  String get description => 'Platform, OS version and app identity.';
  @override
  String get capability => collectorDeviceStatus;
  @override
  String get eventType => 'device.telemetry.state';
  @override
  String get sourceComponent => 'vira_link';
  @override
  Duration get interval => const Duration(minutes: 1);
  @override
  bool get enabledByDefault => true;

  @override
  Future<List<CapturedEvent>> collect(PlatformProbe probe) async {
    final profile = await probe.profile();
    return [
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: {
          'app': appName,
          'client_version': appVersion,
          'protocol_version': protocolVersion,
          'platform': profile.platform,
          'device_type': profile.deviceType,
          'os_version': profile.osVersion,
          'hostname': profile.hostname,
        },
      ),
    ];
  }
}
