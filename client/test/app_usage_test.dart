import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vira_link/core/catalog/app_catalog.dart';
import 'package:vira_link/core/models/app_usage.dart';
import 'package:vira_link/core/models/device_info.dart';
import 'package:vira_link/core/models/device_signals.dart';
import 'package:vira_link/data/storage/session_ledger.dart';
import 'package:vira_link/data/storage/usage_ledger.dart';
import 'package:vira_link/services/capture/android_usage_bridge.dart';
import 'package:vira_link/services/capture/collectors/app_usage_collector.dart';
import 'package:vira_link/services/capture/collectors/battery_collector.dart';
import 'package:vira_link/services/capture/collectors/device_session_collector.dart';
import 'package:vira_link/services/capture/platform_probe_base.dart';

class _FakeProbe implements PlatformProbe {
  _FakeProbe(this.platform);

  final String platform;

  @override
  Future<DeviceProfile> profile() async => DeviceProfile(
    platform: platform,
    deviceType: platform == 'android' ? 'phone' : 'desktop',
    osVersion: 'test',
    hostname: 'test',
  );

  @override
  Future<Map<String, dynamic>?> hardwareSnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> networkSnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> batterySnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> healthSnapshot() async => null;
}

class _FakeSessionSource implements SessionSource {
  _FakeSessionSource({this.permission = true, this.sample});

  bool permission;
  SessionSample? sample;
  bool openedSettings = false;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<bool> openSettings() async {
    openedSettings = true;
    return true;
  }

  @override
  Future<SessionSample?> sessionStats({required Duration lookback}) async =>
      sample;
}

class _FakeBatterySource implements BatterySource {
  _FakeBatterySource(this.snapshot);

  BatterySnapshot? snapshot;

  @override
  Future<BatterySnapshot?> battery() async => snapshot;
}

class _FakeUsageSource implements AppUsageSource {
  _FakeUsageSource({this.permission = true, this.samples = const []});

  bool permission;
  List<AppUsageSample> samples;
  bool openedSettings = false;

  @override
  Future<List<AppUsageSample>> appUsage({required Duration lookback}) async =>
      samples;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<bool> openSettings() async {
    openedSettings = true;
    return true;
  }
}

void main() {
  test('categorises common apps without the server', () {
    expect(
      categoryForApp('com.instagram.android', 'Instagram'),
      AppCategory.social,
    );
    expect(categoryForApp('com.whatsapp', 'WhatsApp'), AppCategory.communication);
    expect(categoryForApp('com.google.android.youtube', 'YouTube'), AppCategory.entertainment);
    expect(categoryForApp('com.android.chrome', 'Chrome'), AppCategory.browsing);
    expect(categoryForApp('com.android.settings', 'Settings'), AppCategory.system);
    expect(categoryForApp('com.example.unknown', 'Thing'), AppCategory.other);
  });

  test('usage ledger merges intervals and days', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await UsageLedger.open();
    final at = DateTime(2026, 1, 2, 10);
    await ledger.record([
      const AppUsageSample(
        packageName: 'com.instagram.android',
        label: 'Instagram',
        foregroundMs: 60000,
        category: AppCategory.social,
      ),
    ], at: at);
    await ledger.record([
      const AppUsageSample(
        packageName: 'com.instagram.android',
        label: 'Instagram',
        foregroundMs: 30000,
        category: AppCategory.social,
      ),
    ], at: at.add(const Duration(minutes: 5)));

    final day = await ledger.day(at);
    expect(day, isNotNull);
    expect(day!.apps['com.instagram.android']!.foregroundMs, 90000);
    expect(day.totalForegroundMs, 90000);
  });

  test('app usage collector emits events and records the ledger', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await UsageLedger.open();
    final source = _FakeUsageSource(
      samples: [
        AppUsageSample(
          packageName: 'com.instagram.android',
          label: 'Instagram',
          foregroundMs: 120000,
          lastUsedAt: DateTime.now().toUtc(),
        ),
        AppUsageSample(
          packageName: 'com.google.android.youtube',
          label: 'YouTube',
          foregroundMs: 60000,
          lastUsedAt: DateTime.now().toUtc(),
        ),
      ],
    );
    final collector = AppUsageCollector(ledger: ledger, source: source);
    final result = await collector.collect(_FakeProbe('android'));

    expect(result.status, 'available');
    expect(result.events, hasLength(2));
    final usageEvent = result.events.firstWhere(
      (event) => event.type == 'device.app.usage',
    );
    final focusEvent = result.events.firstWhere(
      (event) => event.type == 'device.focus.state',
    );
    final apps = usageEvent.payload['apps'] as List;
    expect(apps, hasLength(2));
    expect(apps.first['category'], AppCategory.social);
    expect(usageEvent.payload['total_foreground_ms'], 180000);
    expect(usageEvent.payload['categories'], containsPair(AppCategory.social, 120000));
    expect(focusEvent.payload['state'], 'distracted');
    expect(focusEvent.payload['focus_ms'], 0);

    final today = await ledger.today();
    expect(today.apps['com.google.android.youtube']!.foregroundMs, 60000);
  });

  test('app usage collector reports permission denial', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await UsageLedger.open();
    final source = _FakeUsageSource(permission: false);
    final collector = AppUsageCollector(ledger: ledger, source: source);

    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'permission_denied');
    expect(result.events, isEmpty);
    expect(await collector.requestAccess(), isTrue);
    expect(source.openedSettings, isTrue);
  });

  test('app usage is unavailable outside Android', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await UsageLedger.open();
    final collector = AppUsageCollector(
      ledger: ledger,
      source: _FakeUsageSource(),
    );
    final result = await collector.collect(_FakeProbe('web'));
    expect(result.status, 'unavailable');
  });


  test('session ledger merges screen time and unlocks', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await SessionLedger.open();
    final at = DateTime(2026, 1, 2, 10);
    const sample = SessionSample(
      interactiveMs: 120000,
      screenOnEvents: 1,
      screenOffEvents: 1,
      unlocks: 2,
      interactions: 10,
      currentSessionMs: 60000,
      screenOn: false,
      windowSeconds: 300,
    );
    await ledger.record(sample, at: at);
    await ledger.record(sample, at: at.add(const Duration(minutes: 5)));
    final day = await ledger.day(at);
    expect(day, isNotNull);
    expect(day!.interactiveMs, 240000);
    expect(day.unlocks, 4);
    expect(day.longestSessionMs, 60000);
  });

  test('session collector emits and records Android screen events', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await SessionLedger.open();
    final source = _FakeSessionSource(
      sample: const SessionSample(
        interactiveMs: 180000,
        screenOnEvents: 2,
        screenOffEvents: 1,
        unlocks: 3,
        interactions: 20,
        currentSessionMs: 90000,
        screenOn: true,
        windowSeconds: 300,
      ),
    );
    final collector = DeviceSessionCollector(ledger: ledger, source: source);
    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'available');
    expect(result.events.single.type, 'device.session.state');
    expect(result.events.single.payload['unlocks'], 3);
    final today = await ledger.today();
    expect(today.interactiveMs, 180000);
    expect(today.currentSessionMs, 90000);
  });

  test('session collector reports missing permission', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await SessionLedger.open();
    final collector = DeviceSessionCollector(
      ledger: ledger,
      source: _FakeSessionSource(permission: false),
    );
    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'permission_denied');
  });

  test('battery collector emits Android battery state', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await UsageLedger.open();
    final collector = BatteryCollector(
      source: _FakeBatterySource(
        const BatterySnapshot(
          levelPercent: 72,
          charging: true,
          temperatureC: 31.5,
          plugged: 'usb',
          health: 'good',
        ),
      ),
    );
    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'available');
    expect(result.events.single.payload['level_percent'], 72);
    expect(result.events.single.payload['charging'], true);
    expect(collector.latest?.isLow, isFalse);
    expect(ledger, isNotNull);
  });
}
