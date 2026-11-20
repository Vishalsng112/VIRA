import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/utils/ids.dart';
import '../collector.dart';
import '../desktop_idle_probe.dart';
import '../platform_probe_base.dart';

class IdleCollector extends Collector {
  IdleCollector({DesktopIdleProbe? probe})
    : probe = probe ?? createDesktopIdleProbe();

  final DesktopIdleProbe probe;
  int? latestSeconds;

  @override
  String get id => collectorIdle;
  @override
  String get title => 'Idle state';
  @override
  String get description => 'Active, away and idle time on desktop.';
  @override
  String get capability => collectorIdle;
  @override
  String get eventType => 'device.idle.state';
  @override
  String get sourceComponent => 'idle';
  @override
  Duration get interval => const Duration(minutes: 1);
  @override
  bool get enabledByDefault => true;

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final profile = await probe.profile();
    if (!['linux', 'windows', 'macos'].contains(profile.platform)) {
      return const CollectorResult.unavailable(
        'Idle tracking is available on desktop platforms.',
      );
    }
    final seconds = await this.probe.idleSeconds();
    latestSeconds = seconds;
    if (seconds == null) {
      return const CollectorResult.unavailable(
        'No idle API is available on this desktop session.',
      );
    }
    final state = seconds < 60
        ? 'active'
        : seconds < 300
        ? 'away'
        : 'idle';
    return CollectorResult.available([
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: {
          'app': appName,
          'client_version': appVersion,
          'idle_seconds': seconds,
          'state': state,
        },
      ),
    ]);
  }
}
