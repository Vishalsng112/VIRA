import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vira_link/data/storage/settings_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('diagnostics are opt-in, bounded and clearable', () async {
    SharedPreferences.setMockInitialValues({});
    final store = await SettingsStore.open();

    expect(store.diagnosticsEnabled, isFalse);
    await store.recordDiagnostic({'kind': 'ignored'});
    expect(store.diagnosticEvents(), isEmpty);

    await store.setDiagnosticsEnabled(true);
    expect(store.diagnosticsEnabled, isTrue);
    for (
      var index = 0;
      index < SettingsStore.maxDiagnosticEvents + 4;
      index++
    ) {
      await store.recordDiagnostic({'kind': 'error', 'index': index});
    }
    final events = store.diagnosticEvents();
    expect(events.length, SettingsStore.maxDiagnosticEvents);
    expect(events.first['index'], SettingsStore.maxDiagnosticEvents + 3);
    expect(events.first['captured_at'], isNotNull);

    await store.clearDiagnosticHistory();
    expect(store.diagnosticEvents(), isEmpty);

    await store.setDiagnosticsEnabled(false);
    expect(store.diagnosticsEnabled, isFalse);
  });

  test('break reminders default on and persist', () async {
    SharedPreferences.setMockInitialValues({});
    final store = await SettingsStore.open();
    expect(store.breakRemindersEnabled, isTrue);
    await store.setBreakRemindersEnabled(false);
    expect(store.breakRemindersEnabled, isFalse);
  });

  test('server endpoints persist in order', () async {
    SharedPreferences.setMockInitialValues({});
    final store = await SettingsStore.open();
    expect(store.serverEndpoints, isEmpty);
    await store.setServerEndpoints([
      'https://vira.example.com',
      'http://192.168.1.4:8000',
      'https://vira.example.com',
    ]);
    expect(store.serverEndpoints, [
      'https://vira.example.com',
      'http://192.168.1.4:8000',
    ]);
  });

  test('agent notifications default on and persist', () async {
    SharedPreferences.setMockInitialValues({});
    final store = await SettingsStore.open();
    expect(store.notificationsEnabled, isTrue);
    await store.setNotificationsEnabled(false);
    expect(store.notificationsEnabled, isFalse);
  });

  test('permission setup is one-time and remembers skips', () async {
    SharedPreferences.setMockInitialValues({});
    final store = await SettingsStore.open();

    expect(store.permissionSetupCompleted, isFalse);
    expect(store.notificationPermissionPrompted, isFalse);
    expect(store.usageAccessDismissed, isFalse);

    await store.setNotificationPermissionPrompted(true);
    await store.setUsageAccessDismissed(true);
    await store.setPermissionSetupCompleted(true);

    expect(store.permissionSetupCompleted, isTrue);
    expect(store.notificationPermissionPrompted, isTrue);
    expect(store.usageAccessDismissed, isTrue);

    await store.setUsageAccessDismissed(false);
    expect(store.usageAccessDismissed, isFalse);
  });
}
