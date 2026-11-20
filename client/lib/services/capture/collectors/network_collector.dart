import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/utils/ids.dart';
import '../collector.dart';
import '../platform_probe_base.dart';

/// Interface counts only; raw addresses are not sent.
class NetworkCollector implements Collector {
  @override
  String get id => collectorNetwork;
  @override
  String get title => 'Network';
  @override
  String get description => 'Interface availability and address families.';
  @override
  String get capability => collectorNetwork;
  @override
  String get eventType => 'sensor.network.state';
  @override
  String get sourceComponent => 'network_sensor';
  @override
  Duration get interval => const Duration(minutes: 1);
  @override
  bool get enabledByDefault => true;

  @override
  Future<List<CapturedEvent>> collect(PlatformProbe probe) async {
    final snapshot = await probe.networkSnapshot();
    if (snapshot == null || snapshot.isEmpty) return const [];
    return [
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: snapshot,
      ),
    ];
  }
}
