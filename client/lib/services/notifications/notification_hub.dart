import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../app/app_controller.dart';
import 'firebase_push.dart';
import 'local_notifications.dart';

/// Keeps a live notification stream open while VIRA Link is connected.
///
/// This is the self-hosted transport: new notifications arrive over NDJSON and
/// are surfaced as native notifications. Remote delivery while the app is
/// closed uses the server's push relay channel instead.
class NotificationHub {
  NotificationHub._();

  static final NotificationHub instance = NotificationHub._();

  StreamSubscription<dynamic>? _subscription;
  Timer? _retry;
  AppController? _controller;
  bool _running = false;
  Future<void>? _starting;
  int _attempt = 0;

  bool get running => _running;

  Future<void> start(AppController controller) {
    final starting = _starting;
    if (starting != null) return starting;
    if (_running) return Future.value();
    return _starting = _start(controller);
  }

  Future<void> _start(AppController controller) async {
    _controller = controller;
    _running = true;
    try {
      await LocalNotifications.instance.initialize(
        onOpen: () async => controller.requestModule('inbox'),
      );
      await PushRegistrationService.instance.start(controller);
      if (_running) _connect();
    } on Object catch (error) {
      _running = false;
      debugPrint('Notification hub failed to start: $error');
    } finally {
      _starting = null;
    }
  }

  void stop() {
    _running = false;
    _starting = null;
    _retry?.cancel();
    _retry = null;
    _subscription?.cancel();
    _subscription = null;
  }

  /// Requests notification permission, starting the local notification plugin
  /// first when the first-run permission screen asks before the stream is up.
  Future<bool> requestPermission({AppController? controller}) async {
    if (controller != null) await start(controller);
    final local = await LocalNotifications.instance.requestPermission();
    final push = await PushRegistrationService.instance.requestPermission();
    return local || push;
  }

  void _connect() {
    if (!_running) return;
    final controller = _controller;
    final api = controller?.api;
    if (controller == null || api == null || !controller.isConnected) {
      _scheduleReconnect();
      return;
    }
    _subscription?.cancel();
    _subscription = api.streamNotifications().listen(
      (notification) {
        _attempt = 0;
        LocalNotifications.instance.show(notification);
      },
      onError: (Object error) {
        debugPrint('Notification stream error: $error');
        _scheduleReconnect();
      },
      onDone: _scheduleReconnect,
      cancelOnError: true,
    );
  }

  void _scheduleReconnect() {
    if (!_running || _retry != null) return;
    final seconds = switch (_attempt) {
      0 => 3,
      1 => 10,
      2 => 30,
      _ => 60,
    };
    _attempt = (_attempt + 1).clamp(0, 4);
    _retry = Timer(Duration(seconds: seconds), () {
      _retry = null;
      _connect();
    });
  }
}
