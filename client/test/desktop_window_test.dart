import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vira_link/core/models/device_info.dart';
import 'package:vira_link/data/storage/usage_ledger.dart';
import 'package:vira_link/services/capture/collectors/active_window_collector.dart';
import 'package:vira_link/services/capture/desktop_window_parsers.dart';
import 'package:vira_link/services/capture/desktop_window_probe.dart';
import 'package:vira_link/services/capture/platform_probe_base.dart';

class _FakeProbe implements PlatformProbe {
  @override
  Future<DeviceProfile> profile() async => const DeviceProfile(
    platform: 'linux',
    deviceType: 'desktop',
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

class _FakeWindowProbe implements DesktopWindowProbe {
  _FakeWindowProbe(this.sample);

  DesktopWindowSample? sample;

  @override
  Future<DesktopWindowSample?> activeWindow() async => sample;
}

void main() {
  test('parses Hyprland active window JSON', () {
    final sample = parseHyprlandWindow(
      jsonEncode({
        'class': 'firefox',
        'title': 'Docs - Mozilla Firefox',
        'pid': 42,
      }),
    );
    expect(sample, isNotNull);
    expect(sample!.appId, 'firefox');
    expect(sample.title, contains('Docs'));
    expect(sample.pid, 42);
    expect(sample.method, 'hyprland');
  });

  test('parses focused Sway tree node', () {
    final tree = {
      'type': 'root',
      'focused': false,
      'nodes': [
        {
          'type': 'output',
          'focused': false,
          'nodes': [
            {
              'type': 'con',
              'focused': true,
              'app_id': 'code',
              'name': 'main.dart - Code',
              'pid': 77,
            },
          ],
        },
      ],
    };
    final sample = parseSwayTree(jsonEncode(tree));
    expect(sample, isNotNull);
    expect(sample!.appId, 'code');
    expect(sample.title, contains('main.dart'));
    expect(sample.method, 'sway');
  });

  test('parses KDE queryWindowInfo output', () {
    final sample = parseKdeWindowInfo(
      'caption: Inbox - Thunderbird\nresourceClass: thunderbird\npid: 88\n',
    );
    expect(sample, isNotNull);
    expect(sample!.appId, 'thunderbird');
    expect(sample.title, contains('Inbox'));
    expect(sample.pid, 88);
  });

  test('parses GNOME extension D-Bus output', () {
    final sample = parseGnomeExtensionWindow(
      "('{\"app_id\":\"org.gnome.Nautilus\",\"title\":\"Home\",\"pid\":99}',)",
    );
    expect(sample, isNotNull);
    expect(sample!.appId, 'org.gnome.Nautilus');
    expect(sample.title, 'Home');
    expect(sample.method, 'gnome-extension');
  });

  test('parses Windows foreground window JSON', () {
    final sample = parseWindowsWindow(
      '{"app":"Code","title":"roadmap.md - Visual Studio Code","pid":123}',
    );
    expect(sample, isNotNull);
    expect(sample!.appId, 'Code');
    expect(sample.title, contains('roadmap.md'));
    expect(sample.method, 'windows-foreground');
  });

  test('parses macOS frontmost app output', () {
    final sample = parseMacOsWindow(
      'Safari\ncom.apple.Safari\n321\nVIRA docs\n',
    );
    expect(sample, isNotNull);
    expect(sample!.appId, 'com.apple.Safari');
    expect(sample.appName, 'Safari');
    expect(sample.title, 'VIRA docs');
    expect(sample.method, 'macos-frontmost');
  });

  test('parses X11 active window and properties', () {
    expect(
      parseX11ActiveWindowId('_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4a00007'),
      '0x4a00007',
    );
    final sample = parseX11Properties(
      'WM_CLASS(STRING) = "Navigator", "firefox"\n'
      '_NET_WM_NAME(UTF8_STRING) = "Docs"\n'
      '_NET_WM_PID(CARDINAL) = 55\n',
    );
    expect(sample, isNotNull);
    expect(sample!.appId, 'firefox');
    expect(sample.title, 'Docs');
    expect(sample.pid, 55);
    expect(sample.method, 'x11-xprop');
  });

  test('active window collector records desktop usage and emits events', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await UsageLedger.open();
    final windowProbe = _FakeWindowProbe(
      const DesktopWindowSample(
        appId: 'firefox',
        appName: 'Firefox',
        title: 'Docs',
        pid: 10,
        method: 'test',
      ),
    );
    var now = DateTime(2026, 1, 1, 10);
    final collector = ActiveWindowCollector(
      ledger: ledger,
      probe: windowProbe,
      clock: () => now,
      emitEvery: Duration.zero,
    );
    final probe = _FakeProbe();

    final first = await collector.collect(probe);
    expect(first.events, isEmpty);

    now = now.add(const Duration(minutes: 1));
    final second = await collector.collect(probe);
    expect(second.events, hasLength(2));
    final usage = second.events.firstWhere(
      (event) => event.type == 'device.app.usage',
    );
    expect(usage.payload['capture_method'], 'desktop_active_window');
    final apps = usage.payload['apps'] as List;
    expect(apps.single['package'], 'firefox');
    expect(apps.single['foreground_ms'], 60000);

    final day = await ledger.day(now);
    expect(day!.apps['firefox']!.foregroundMs, 60000);
  });

  test('desktop probe is safe when no compositor API is present', () async {
    final probe = createDesktopWindowProbe();
    final result = await probe.activeWindow();
    expect(result == null || result.appId.isNotEmpty, isTrue);
  });
}
