import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:vira_link/core/models/pairing_code.dart';

void main() {
  test('parses a vira pairing deep link', () {
    final payload = PairingPayload.tryParse(
      'vira://pair?server=http%3A%2F%2F192.168.1.20%3A8000&code=abcd-2345&provider=tailscale',
    );
    expect(payload, isNotNull);
    expect(payload!.server, 'http://192.168.1.20:8000');
    expect(payload.code, 'ABCD2345');
    expect(payload.provider, 'tailscale');
  });

  test('parses an http link with pairing parameters', () {
    final payload = PairingPayload.tryParse(
      'https://vira.local:8000/pair?server=https%3A%2F%2Fvira.local%3A8000&code=WXYZ6789',
    );
    expect(payload?.server, 'https://vira.local:8000');
    expect(payload?.code, 'WXYZ6789');
  });

  test('accepts a bare code without a server', () {
    final payload = PairingPayload.tryParse(' abcd 2345 ');
    expect(payload?.server, isEmpty);
    expect(payload?.code, 'ABCD2345');
  });

  test('parses the LAN and tunnel endpoint list', () {
    final endpoints = base64Url
        .encode(
          utf8.encode(
            jsonEncode([
              {'kind': 'cloudflare', 'url': 'https://vira.example.com'},
              {'kind': 'lan', 'url': 'http://192.168.1.4:8000'},
            ]),
          ),
        )
        .replaceAll('=', '');
    final payload = PairingPayload.tryParse(
      'vira://pair?server=https%3A%2F%2Fvira.example.com&code=ABCD2345&provider=cloudflare&endpoints=$endpoints',
    );
    expect(payload, isNotNull);
    expect(payload!.endpoints.map((item) => item.kind), ['cloudflare', 'lan']);
    expect(payload.endpoints.first.url, 'https://vira.example.com');
    expect(payload.endpoints.last.url, 'http://192.168.1.4:8000');
  });

  test('rejects unrelated text and wrong-length codes', () {
    expect(PairingPayload.tryParse('hello world'), isNull);
    expect(PairingPayload.tryParse('ABC123'), isNull);
    expect(PairingPayload.tryParse('AB01CDEF'), isNull);
  });
}
