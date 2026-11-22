import 'device_info.dart';

/// A pairing link or code shown by the VIRA server dashboard.
class PairingPayload {
  const PairingPayload({required this.server, required this.code});

  final String server;
  final String code;

  static final _codePattern = RegExp(r'^[A-Z2-9]{8}$');

  /// Extracts the server and code from a `vira://pair?...` link, an HTTP link
  /// that carries `server` and `code` query parameters, or a bare code.
  static PairingPayload? tryParse(String raw) {
    final value = raw.trim();
    if (value.isEmpty) return null;

    final uri = Uri.tryParse(value);
    if (uri != null && uri.hasQuery) {
      final server = uri.queryParameters['server']?.trim();
      final code = normalizeCode(uri.queryParameters['code'] ?? '');
      if (server != null && server.isNotEmpty && code != null) {
        return PairingPayload(server: server, code: code);
      }
    }

    final code = normalizeCode(value);
    if (code != null) return PairingPayload(server: '', code: code);
    return null;
  }

  /// Uppercases a code and drops separators such as spaces and dashes.
  static String? normalizeCode(String raw) {
    final code = raw.replaceAll(RegExp(r'[^A-Za-z0-9]'), '').toUpperCase();
    return _codePattern.hasMatch(code) ? code : null;
  }
}

/// The device credential and user session returned by the pairing endpoint.
class PairingResult {
  const PairingResult({
    required this.device,
    required this.token,
    required this.sessionId,
    required this.username,
    required this.roles,
  });

  final DeviceInfo device;
  final String token;
  final String? sessionId;
  final String? username;
  final List<String> roles;

  bool get isAdmin => roles.contains('admin');
}
