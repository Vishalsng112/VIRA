import 'package:flutter_test/flutter_test.dart';
import 'package:vira_link/core/models/device_info.dart';
import 'package:vira_link/core/models/device_signals.dart';
import 'package:vira_link/services/capture/android_usage_bridge.dart';
import 'package:vira_link/services/capture/collectors/health_collector.dart';
import 'package:vira_link/services/capture/collectors/idle_collector.dart';
import 'package:vira_link/services/capture/desktop_idle_probe_base.dart';
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
  Future<Map<String, dynamic>?> batterySnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> hardwareSnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> networkSnapshot() async => null;

  @override
  Future<Map<String, dynamic>?> healthSnapshot() async => null;
}

class _FakeHealthSource implements HealthSource {
  _FakeHealthSource(this.snapshot);

  DeviceHealthSnapshot? snapshot;

  @override
  Future<DeviceHealthSnapshot?> health() async => snapshot;
}

class _FakeIdleProbe implements DesktopIdleProbe {
  _FakeIdleProbe(this.seconds);

  int? seconds;

  @override
  Future<int?> idleSeconds() async => seconds;
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

void main() {
  test('health collector emits storage and thermal warnings', () async {
    final collector = HealthCollector(
      source: _FakeHealthSource(
        const DeviceHealthSnapshot(
          storageFreeBytes: 5,
          storageTotalBytes: 100,
          memoryAvailableBytes: 10,
          memoryTotalBytes: 100,
          thermalC: 47,
        ),
      ),
    );
    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'available');
    expect(result.events.single.type, 'device.health.state');
    expect(result.events.single.payload['storage_percent'], 95);
    expect(result.events.single.payload['thermal_c'], 47);
    expect(result.events.single.payload['warnings'], isNotEmpty);
    expect(collector.latest?.storageLow, isTrue);
  });

  test('idle collector maps active/away/idle states', () async {
    final probe = _FakeIdleProbe(30);
    final collector = IdleCollector(probe: probe);
    var result = await collector.collect(_FakeProbe('linux'));
    expect(result.events.single.payload['state'], 'active');

    probe.seconds = 120;
    result = await collector.collect(_FakeProbe('linux'));
    expect(result.events.single.payload['state'], 'away');

    probe.seconds = 900;
    result = await collector.collect(_FakeProbe('linux'));
    expect(result.events.single.payload['state'], 'idle');
  });

  test('idle collector uses Android session data when permitted', () async {
    final source = _FakeSessionSource(
      sample: const SessionSample(
        interactiveMs: 0,
        screenOnEvents: 0,
        screenOffEvents: 1,
        unlocks: 0,
        interactions: 0,
        currentSessionMs: 0,
        screenOn: false,
        windowSeconds: 60,
      ),
    );
    final collector = IdleCollector(sessionSource: source);
    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'available');
    expect(result.events.single.payload['state'], 'idle');
    expect(result.events.single.payload['platform'], 'android');
    expect(result.events.single.payload['idle_seconds'], 60);
  });

  test('idle collector reports Android permission denial', () async {
    final collector = IdleCollector(
      sessionSource: _FakeSessionSource(permission: false),
    );
    final result = await collector.collect(_FakeProbe('android'));
    expect(result.status, 'permission_denied');
  });

  test('idle collector is unavailable outside desktop and Android', () async {
    final collector = IdleCollector(probe: _FakeIdleProbe(30));
    final result = await collector.collect(_FakeProbe('ios'));
    expect(result.status, 'unavailable');
  });
}
