import '../../core/models/captured_event.dart';
import 'platform_probe_base.dart';

/// A capture module. Add a collector by implementing this interface and adding
/// it to the list in [CaptureService]; remove it from that list to remove the
/// feature. Collectors never talk to the network: they only produce events that
/// the outbox stores.
abstract class Collector {
  String get id;
  String get title;
  String get description;
  String get capability;
  String get eventType;
  String get sourceComponent;
  Duration get interval;
  bool get enabledByDefault;

  Future<List<CapturedEvent>> collect(PlatformProbe probe);
}
