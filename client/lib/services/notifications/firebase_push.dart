import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import '../../app/app_controller.dart';
import '../../core/models/agent_inbox.dart';
import 'local_notifications.dart';

const _apiKey = String.fromEnvironment('VIRA_FIREBASE_API_KEY');
const _appId = String.fromEnvironment('VIRA_FIREBASE_APP_ID');
const _senderId = String.fromEnvironment('VIRA_FIREBASE_MESSAGING_SENDER_ID');
const _projectId = String.fromEnvironment('VIRA_FIREBASE_PROJECT_ID');
const _storageBucket = String.fromEnvironment('VIRA_FIREBASE_STORAGE_BUCKET');
const _authDomain = String.fromEnvironment('VIRA_FIREBASE_AUTH_DOMAIN');
const _iosBundleId = String.fromEnvironment('VIRA_FIREBASE_IOS_BUNDLE_ID');
const _vapidKey = String.fromEnvironment('VIRA_FIREBASE_VAPID_KEY');

@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {
  // FCM notification payloads are displayed by the operating system. Data-only
  // messages deliberately do nothing so the app does not wake for work it
  // cannot show.
}

/// Registers this device for remote push when Firebase options are provided.
class PushRegistrationService {
  PushRegistrationService._();

  static final PushRegistrationService instance = PushRegistrationService._();

  bool _initialized = false;
  bool _available = false;
  AppController? _controller;

  bool get available => _available;

  FirebaseOptions? _options() {
    if (_apiKey.isEmpty ||
        _appId.isEmpty ||
        _senderId.isEmpty ||
        _projectId.isEmpty) {
      return null;
    }
    return FirebaseOptions(
      apiKey: _apiKey,
      appId: _appId,
      messagingSenderId: _senderId,
      projectId: _projectId,
      storageBucket: _storageBucket.isEmpty ? null : _storageBucket,
      authDomain: _authDomain.isEmpty ? null : _authDomain,
      iosBundleId: _iosBundleId.isEmpty ? null : _iosBundleId,
    );
  }

  Future<bool> initialize() async {
    if (_initialized) return _available;
    _initialized = true;
    final options = _options();
    if (options == null) return false;
    try {
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp(options: options);
      }
      FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);
      _available = true;
    } on Object catch (error) {
      debugPrint('Firebase push unavailable: $error');
      _available = false;
    }
    return _available;
  }

  Future<bool> requestPermission() async {
    if (!await initialize()) return false;
    try {
      final settings = await FirebaseMessaging.instance.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );
      final granted =
          settings.authorizationStatus == AuthorizationStatus.authorized ||
          settings.authorizationStatus == AuthorizationStatus.provisional;
      if (granted && _controller != null) await _register(_controller!);
      return granted;
    } on Object catch (error) {
      debugPrint('Push permission request failed: $error');
      return false;
    }
  }

  Future<void> start(AppController controller) async {
    _controller = controller;
    if (!await initialize()) return;
    try {
      await FirebaseMessaging.instance.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );
      await _register(controller);
      // ignore: deprecated_member_use
      FirebaseMessaging.instance.onTokenRefresh.listen((token) {
        _sendToken(controller, token);
      });
      FirebaseMessaging.onMessage.listen((message) {
        if (controller.notificationsEnabled) {
          LocalNotifications.instance.show(_fromRemote(message));
        }
      });
      FirebaseMessaging.onMessageOpenedApp.listen((_) {
        controller.requestModule('inbox');
      });
      final initial = await FirebaseMessaging.instance.getInitialMessage();
      if (initial != null) controller.requestModule('inbox');
    } on Object catch (error) {
      debugPrint('Push registration failed: $error');
    }
  }

  Future<void> _register(AppController controller) async {
    // Token-based FCM v1 targeting is the contract the server implements.
    // ignore: deprecated_member_use
    final token = await FirebaseMessaging.instance.getToken(
      vapidKey: _vapidKey.isEmpty ? null : _vapidKey,
    );
    if (token != null) await _sendToken(controller, token);
  }

  Future<void> _sendToken(AppController controller, String token) async {
    final api = controller.api;
    if (api == null || api.deviceId == null) return;
    final platform = kIsWeb ? 'web' : defaultTargetPlatform.name;
    try {
      await api.registerPushToken(platform: platform, token: token);
      debugPrint('Registered remote push token for $platform');
    } on Object catch (error) {
      debugPrint('Could not register push token: $error');
    }
  }

  AgentNotification _fromRemote(RemoteMessage message) {
    return AgentNotification(
      id: message.messageId ?? DateTime.now().microsecondsSinceEpoch.toString(),
      title:
          message.notification?.title ??
          message.data['title'] ??
          'Agent update',
      body: message.notification?.body ?? message.data['body'] ?? '',
      kind: 'agent_schedule',
      status: 'delivered',
      channel: 'push',
      data: message.data,
      createdAt: DateTime.now(),
    );
  }
}
