import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/models/device_signals.dart';
import '../../../core/utils/ids.dart';
import '../android_usage_bridge.dart';
import '../collector.dart';
import '../platform_probe_base.dart';

/// Storage, memory, thermal and battery-temperature health signals.
class HealthCollector extends Collector {
  HealthCollector({HealthSource? source}) : source = source ?? AndroidUsageBridge();

  final HealthSource source;
  DeviceHealthSnapshot? latest;

  @override
  String get id => collectorDeviceHealth;
  @override
  String get title => 'Device health';
  @override
  String get description => 'Storage, memory, thermal and power warnings.';
  @override
  String get capability => collectorDeviceHealth;
  @override
  String get eventType => 'device.health.state';
  @override
  String get sourceComponent => 'device_health';
  @override
  Duration get interval => const Duration(minutes: 10);
  @override
  bool get enabledByDefault => true;

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final profile = await probe.profile();
    DeviceHealthSnapshot? snapshot;
    if (profile.platform == 'android') {
      snapshot = await source.health();
    } else {
      final raw = await probe.healthSnapshot();
      if (raw != null) snapshot = DeviceHealthSnapshot.fromJson(raw);
    }
    latest = snapshot;
    if (snapshot == null) {
      return const CollectorResult.unavailable(
        'Device health data is not available on this platform.',
      );
    }
    return CollectorResult.available([
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: {
          'app': appName,
          'client_version': appVersion,
          ...snapshot.toJson(),
        },
      ),
    ]);
  }
}
