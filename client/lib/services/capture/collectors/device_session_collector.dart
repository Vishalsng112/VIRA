import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../data/storage/session_ledger.dart';
import '../../../core/utils/ids.dart';
import '../android_usage_bridge.dart';
import '../collector.dart';
import '../platform_probe_base.dart';

/// Screen interactive time, unlocks and current session length.
///
/// Uses Android UsageStats events (screen interactive/non-interactive, keyguard
/// and user interaction) so no extra permission or background service is
/// needed beyond Usage Access.
class DeviceSessionCollector extends Collector {
  DeviceSessionCollector({
    required this.ledger,
    SessionSource? source,
  }) : source = source ?? AndroidUsageBridge();

  final SessionLedger ledger;
  final SessionSource source;

  @override
  String get id => collectorScreenSession;
  @override
  String get title => 'Screen & sessions';
  @override
  String get description => 'Screen time, unlocks and current session.';
  @override
  String get capability => collectorScreenSession;
  @override
  String get eventType => 'device.session.state';
  @override
  String get sourceComponent => 'screen_session';
  @override
  Duration get interval => const Duration(minutes: 5);
  @override
  bool get enabledByDefault => true;
  @override
  bool get canRequestAccess => true;

  @override
  Future<bool> requestAccess() => source.openSettings();

  @override
  bool get hasLocalData => true;

  @override
  Future<void> clearLocalData() => ledger.clear();

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final profile = await probe.profile();
    if (profile.platform != 'android') {
      return const CollectorResult.unavailable(
        'Screen/session tracking is Android-only for now; desktop idle tracking is on the roadmap.',
      );
    }
    if (!await source.hasPermission()) {
      return const CollectorResult.permissionDenied(
        'Grant Usage Access so VIRA Link can read screen/session events.',
      );
    }
    final sample = await source.sessionStats(lookback: interval);
    if (sample == null) {
      return const CollectorResult.degraded(
        'The system did not return screen/session data.',
      );
    }
    await ledger.record(sample);
    return CollectorResult.available([
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: {
          'app': appName,
          'client_version': appVersion,
          ...sample.toJson(),
        },
      ),
    ]);
  }
}
