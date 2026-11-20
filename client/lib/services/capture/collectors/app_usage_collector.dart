import '../../../core/catalog/app_catalog.dart';
import '../../../core/config/app_config.dart';
import '../../../data/storage/usage_ledger.dart';
import '../android_usage_bridge.dart';
import '../collector.dart';
import '../platform_probe_base.dart';
import '../usage_events.dart';

/// Foreground application time from Android UsageStatsManager.
///
/// The collector emits one aggregated event per interval and also updates the
/// local daily ledger so Insights works offline.
class AppUsageCollector extends Collector {
  AppUsageCollector({
    required this.ledger,
    AppUsageSource? source,
  }) : source = source ?? AndroidUsageBridge();

  final UsageLedger ledger;
  final AppUsageSource source;

  @override
  String get id => collectorAppUsage;
  @override
  String get title => 'App usage';
  @override
  String get description => 'Foreground time per application (Android).';
  @override
  String get capability => collectorAppUsage;
  @override
  String get eventType => 'device.app.usage';
  @override
  String get sourceComponent => 'app_usage';
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
        'App usage is Android-only for now; desktop active-window capture is on the roadmap.',
      );
    }
    if (!await source.hasPermission()) {
      return const CollectorResult.permissionDenied(
        'Grant Usage Access so VIRA Link can measure foreground app time.',
      );
    }

    final raw = await source.appUsage(lookback: interval);
    if (raw.isEmpty) {
      return const CollectorResult.available([]);
    }
    final samples = raw
        .map(
          (sample) => sample.copyWith(
            category: categoryForApp(sample.packageName, sample.label),
          ),
        )
        .toList()
      ..sort((a, b) => b.foregroundMs.compareTo(a.foregroundMs));
    final limited = samples.take(80).toList();
    await ledger.record(limited);

    return CollectorResult.available(
      buildUsageEvents(
        samples: samples,
        windowSeconds: interval.inSeconds,
        captureMethod: 'android_usage_stats',
        platform: profile.platform,
      ),
    );
  }
}