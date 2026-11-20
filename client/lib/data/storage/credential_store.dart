import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// The device credential is shown by the server exactly once. It is kept in the
/// platform keystore/keychain (or the browser's secure storage backend), never
/// in SharedPreferences and never in logs or UI.
class StoredCredentials {
  const StoredCredentials({
    this.serverUrl,
    this.username,
    this.sessionId,
    this.deviceId,
    this.deviceToken,
  });

  final String? serverUrl;
  final String? username;
  final String? sessionId;
  final String? deviceId;
  final String? deviceToken;

  bool get hasDevice => serverUrl != null && deviceId != null && deviceToken != null;
  bool get hasSession => sessionId != null;
}

class CredentialStore {
  CredentialStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _serverKey = 'vira_link.server';
  static const _usernameKey = 'vira_link.username';
  static const _sessionKey = 'vira_link.session_id';
  static const _deviceIdKey = 'vira_link.device_id';
  static const _deviceTokenKey = 'vira_link.device_token';

  final FlutterSecureStorage _storage;

  Future<StoredCredentials> load() async => StoredCredentials(
    serverUrl: await _storage.read(key: _serverKey),
    username: await _storage.read(key: _usernameKey),
    sessionId: await _storage.read(key: _sessionKey),
    deviceId: await _storage.read(key: _deviceIdKey),
    deviceToken: await _storage.read(key: _deviceTokenKey),
  );

  Future<void> save({
    required String serverUrl,
    required String username,
    required String sessionId,
    required String deviceId,
    required String deviceToken,
  }) async {
    await Future.wait([
      _storage.write(key: _serverKey, value: serverUrl),
      _storage.write(key: _usernameKey, value: username),
      _storage.write(key: _sessionKey, value: sessionId),
      _storage.write(key: _deviceIdKey, value: deviceId),
      _storage.write(key: _deviceTokenKey, value: deviceToken),
    ]);
  }

  Future<void> clear() async {
    await Future.wait([
      _storage.delete(key: _serverKey),
      _storage.delete(key: _usernameKey),
      _storage.delete(key: _sessionKey),
      _storage.delete(key: _deviceIdKey),
      _storage.delete(key: _deviceTokenKey),
    ]);
  }
}
