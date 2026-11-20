import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/utils/ids.dart';
import '../collector.dart';
import '../platform_probe_base.dart';

/// CPU and memory where the platform exposes them (currently Linux). Other
/// platforms return null and the capability is reported as unavailable.
class HardwareCollector extends Collector {
  @override
  String get id => collectorHardware;
  @override
  String get title => 'Hardware';
  @override
  String get description => 'CPU and memory usage.';
  @override
  String get capability => collectorHardware;
  @override
  String get eventType => 'sensor.hardware.state';
  @override
  String get sourceComponent => 'hardware_sensor';
  @override
  Duration get interval => const Duration(seconds: 30);
  @override
  bool get enabledByDefault => true;

  @override
  bool get canRequestAccess => false;

  @override
  Future<bool> requestAccess() async => false;

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final snapshot = await probe.hardwareSnapshot();
    if (snapshot == null || snapshot.isEmpty) {
      return const CollectorResult.unavailable(
        'This platform does not expose the signal yet.',
      );
    }
    return CollectorResult.available([
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: snapshot,
      ),
    ]);
  }
}
