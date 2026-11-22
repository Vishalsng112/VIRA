import 'dart:convert';

import 'device_info.dart';

/// One reachable server address carried by a pairing link.
class PairingEndpoint {
  const PairingEndpoint({required this.kind, required this.url});

  final String kind;
  final String url;

  static PairingEndpoint? tryParse(Object? value) {
    if (value is! Map) return null;
    final kind = value['kind']?.toString().trim() ?? '';
    final raw = value['url']?.toString().trim() ?? '';
    if (kind.isEmpty || raw.isEmpty) return null;
    final uri = Uri.tryParse(raw);
    if (uri == null || !uri.hasScheme || !uri.hasAuthority) return null;
    if (uri.scheme != 'http' && uri.scheme != 'https') return null;
    return PairingEndpoint(
      kind: kind,
      url: raw.replaceFirst(RegExp(r'/+$'), ''),
    );
  }
}

/// A pairing link or code shown by the VIRA server dashboard.
class PairingPayload {
  const PairingPayload({
    required this.server,
    required this.code,
    this.provider,
    this.endpoints = const [],
  });

  final String server;
  final String code;

  /// The server-side access provider such as `cloudflare`, `lan` or `tailscale`.
  final String? provider;

  /// Every reachable address, in server preference order.
  final List<PairingEndpoint> endpoints;

  static final _codePattern = RegExp(r'^[A-Z2-9]{8}$');

  /// Extracts the server, code and endpoint list from a `vira://pair?...`
  /// link, an HTTP link carrying `server`/`code`, or a bare code.
  static PairingPayload? tryParse(String raw) {
    final value = raw.trim();
    if (value.isEmpty) return null;

    final uri = Uri.tryParse(value);
    if (uri != null && uri.hasQuery) {
      final server = uri.queryParameters['server']?.trim();
      final code = normalizeCode(uri.queryParameters['code'] ?? '');
      if (server != null && server.isNotEmpty && code != null) {
        final endpoints = _decodeEndpoints(uri.queryParameters['endpoints']);
        return PairingPayload(
          server: server.replaceFirst(RegExp(r'/+$'), ''),
          code: code,
          provider: uri.queryParameters['provider'],
          endpoints: _withPrimary(endpoints, server),
        );
      }
    }

    final code = normalizeCode(value);
    if (code != null) return PairingPayload(server: '', code: code);
    return null;
  }

  static List<PairingEndpoint> _decodeEndpoints(String? encoded) {
    if (encoded == null || encoded.trim().isEmpty) return const [];
    try {
      final normalized = base64Url.normalize(encoded.trim());
      final decoded = utf8.decode(base64Url.decode(normalized));
      final data = jsonDecode(decoded);
      if (data is! List) return const [];
      return data
          .map(PairingEndpoint.tryParse)
          .whereType<PairingEndpoint>()
          .toList();
    } on FormatException {
      return const [];
    }
  }

  static List<PairingEndpoint> _withPrimary(
    List<PairingEndpoint> endpoints,
    String server,
  ) {
    final normalized = server.replaceFirst(RegExp(r'/+$'), '');
    final result = <PairingEndpoint>[];
    final seen = <String>{};
    for (final endpoint in endpoints) {
      if (seen.add(endpoint.url)) result.add(endpoint);
    }
    if (result.every((endpoint) => endpoint.url != normalized)) {
      result.insert(0, PairingEndpoint(kind: 'primary', url: normalized));
    }
    return result;
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
