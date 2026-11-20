import '../../core/models/captured_event.dart';
import 'platform_probe_base.dart';

class CollectorResult {
  const CollectorResult({
    required this.events,
    this.status = 'available',
    this.message,
  });

  const CollectorResult.available(this.events)
    : status = 'available',
      message = null;

  const CollectorResult.unavailable(String this.message)
    : events = const [],
      status = 'unavailable';

  const CollectorResult.permissionDenied(String this.message)
    : events = const [],
      status = 'permission_denied';

  const CollectorResult.degraded(String this.message)
    : events = const [],
      status = 'degraded';

  final List<CapturedEvent> events;
  final String status;
  final String? message;
}

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

  /// True when the collector can open an OS settings page to request access.
  bool get canRequestAccess => false;

  Future<CollectorResult> collect(PlatformProbe probe);

  Future<bool> requestAccess() async => false;

  /// True when the collector owns a local ledger that can be cleared.
  bool get hasLocalData => false;

  Future<void> clearLocalData() async {}
}
