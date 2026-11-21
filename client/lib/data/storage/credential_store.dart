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
    this.isAdmin = false,
  });

  final String? serverUrl;
  final String? username;
  final String? sessionId;
  final String? deviceId;
  final String? deviceToken;
  final bool isAdmin;

  bool get hasDevice =>
      serverUrl != null && deviceId != null && deviceToken != null;
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
  static const _isAdminKey = 'vira_link.is_admin';

  final FlutterSecureStorage _storage;

  Future<StoredCredentials> load() async => StoredCredentials(
    serverUrl: await _storage.read(key: _serverKey),
    username: await _storage.read(key: _usernameKey),
    sessionId: await _storage.read(key: _sessionKey),
    deviceId: await _storage.read(key: _deviceIdKey),
    deviceToken: await _storage.read(key: _deviceTokenKey),
    isAdmin: (await _storage.read(key: _isAdminKey)) == 'true',
  );

  Future<void> save({
    required String serverUrl,
    required String username,
    required String sessionId,
    required String deviceId,
    required String deviceToken,
    bool isAdmin = false,
  }) async {
    await Future.wait([
      _storage.write(key: _serverKey, value: serverUrl),
      _storage.write(key: _usernameKey, value: username),
      _storage.write(key: _sessionKey, value: sessionId),
      _storage.write(key: _deviceIdKey, value: deviceId),
      _storage.write(key: _deviceTokenKey, value: deviceToken),
      _storage.write(key: _isAdminKey, value: isAdmin ? 'true' : 'false'),
    ]);
  }

  Future<void> clearDevice() async {
    await Future.wait([
      _storage.delete(key: _deviceIdKey),
      _storage.delete(key: _deviceTokenKey),
    ]);
  }

  Future<void> clear() async {
    await Future.wait([
      _storage.delete(key: _serverKey),
      _storage.delete(key: _usernameKey),
      _storage.delete(key: _sessionKey),
      _storage.delete(key: _deviceIdKey),
      _storage.delete(key: _deviceTokenKey),
      _storage.delete(key: _isAdminKey),
    ]);
  }
}
