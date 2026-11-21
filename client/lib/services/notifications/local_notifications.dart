import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../../core/models/agent_inbox.dart';

/// Thin wrapper around the platform notification plugin.
class LocalNotifications {
  LocalNotifications._();

  static final LocalNotifications instance = LocalNotifications._();

  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  bool _ready = false;

  Future<void> initialize({required Future<void> Function() onOpen}) async {
    if (_ready) return;
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(),
      macOS: DarwinInitializationSettings(),
      linux: LinuxInitializationSettings(defaultActionName: 'Open VIRA'),
      windows: WindowsInitializationSettings(
        appName: 'VIRA Link',
        appUserModelId: 'Vira.Link.AgentInbox',
        guid: 'd8e6f6b4-2a3c-4f1d-9d8e-6b1f2a7c3e5f',
      ),
      web: WebInitializationSettings(),
    );
    try {
      await _plugin.initialize(
        settings: settings,
        onDidReceiveNotificationResponse: (_) => onOpen(),
      );
      _ready = true;
    } on Object catch (error) {
      debugPrint('Native notifications unavailable: $error');
      _ready = false;
    }
  }

  Future<bool> requestPermission() async {
    if (!_ready) return false;
    try {
      if (kIsWeb) {
        final web = _plugin
            .resolvePlatformSpecificImplementation<
              WebFlutterLocalNotificationsPlugin
            >();
        return await web?.requestNotificationsPermission() ?? false;
      }
      switch (defaultTargetPlatform) {
        case TargetPlatform.android:
          final android = _plugin
              .resolvePlatformSpecificImplementation<
                AndroidFlutterLocalNotificationsPlugin
              >();
          return await android?.requestNotificationsPermission() ?? false;
        case TargetPlatform.iOS:
          final ios = _plugin
              .resolvePlatformSpecificImplementation<
                IOSFlutterLocalNotificationsPlugin
              >();
          return await ios?.requestPermissions(
                alert: true,
                badge: true,
                sound: true,
              ) ??
              false;
        case TargetPlatform.macOS:
          final macos = _plugin
              .resolvePlatformSpecificImplementation<
                MacOSFlutterLocalNotificationsPlugin
              >();
          return await macos?.requestPermissions(
                alert: true,
                badge: true,
                sound: true,
              ) ??
              false;
        default:
          return true;
      }
    } on Object catch (error) {
      debugPrint('Notification permission request failed: $error');
      return false;
    }
  }

  Future<void> show(AgentNotification notification) async {
    if (!_ready) return;
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'vira_agent_updates',
        'Agent updates',
        channelDescription: 'Results from scheduled VIRA agents',
        importance: Importance.high,
        priority: Priority.high,
      ),
      iOS: DarwinNotificationDetails(),
      macOS: DarwinNotificationDetails(),
    );
    try {
      await _plugin.show(
        id: notification.id.hashCode & 0x7fffffff,
        title: notification.title,
        body: notification.body,
        notificationDetails: details,
        payload: 'inbox',
      );
    } on Object catch (error) {
      debugPrint('Could not show native notification: $error');
    }
  }
}
