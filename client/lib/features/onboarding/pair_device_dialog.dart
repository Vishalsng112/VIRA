import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../app/app_controller.dart';
import '../../core/models/pairing_code.dart';

/// Lets the user redeem a single-use pairing code from the server dashboard.
Future<bool> showPairDeviceDialog(
  BuildContext context, {
  required AppController controller,
  required String initialServer,
}) async {
  final paired = await showDialog<bool>(
    context: context,
    builder: (context) =>
        _PairDeviceDialog(controller: controller, initialServer: initialServer),
  );
  return paired ?? false;
}

class _PairDeviceDialog extends StatefulWidget {
  const _PairDeviceDialog({
    required this.controller,
    required this.initialServer,
  });

  final AppController controller;
  final String initialServer;

  @override
  State<_PairDeviceDialog> createState() => _PairDeviceDialogState();
}

class _PairDeviceDialogState extends State<_PairDeviceDialog> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _server;
  final _code = TextEditingController();
  late final TextEditingController _deviceName;
  String? _error;
  bool _busy = false;
  List<PairingEndpoint> _endpoints = const [];

  bool get _canScan =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  @override
  void initState() {
    super.initState();
    _server = TextEditingController(text: widget.initialServer);
    _deviceName = TextEditingController(
      text: widget.controller.suggestedDeviceName,
    );
  }

  @override
  void dispose() {
    _server.dispose();
    _code.dispose();
    _deviceName.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final raw = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (context) => const _QrScannerPage()),
    );
    if (raw == null || !mounted) return;
    final payload = PairingPayload.tryParse(raw);
    if (payload == null) {
      setState(() => _error = 'That QR code is not a VIRA pairing code.');
      return;
    }
    setState(() {
      _error = null;
      _endpoints = payload.endpoints;
      if (payload.server.isNotEmpty) _server.text = payload.server;
      _code.text = payload.code;
    });
  }

  void _onCodeChanged(String value) {
    if (!value.contains('://') && !value.contains('?')) {
      if (_endpoints.isNotEmpty) setState(() => _endpoints = const []);
      return;
    }
    final payload = PairingPayload.tryParse(value);
    if (payload == null || payload.server.isEmpty) return;
    setState(() {
      _endpoints = payload.endpoints;
      _server.text = payload.server;
      _code.text = payload.code;
    });
  }

  Future<void> _submit() async {
    if (!(_form.currentState?.validate() ?? false)) return;
    final payload = PairingPayload.tryParse(_code.text);
    if (payload == null) return;
    final server = payload.server.isEmpty ? _server.text : payload.server;
    if (payload.server.isNotEmpty && _server.text != payload.server) {
      _server.text = payload.server;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    await widget.controller.pairDevice(
      server: server,
      code: payload.code,
      deviceName: _deviceName.text,
      endpoints: payload.endpoints.isEmpty ? _endpoints : payload.endpoints,
    );
    if (!mounted) return;
    if (widget.controller.isConnected) {
      Navigator.of(context).pop(true);
      return;
    }
    setState(() {
      _busy = false;
      _error = widget.controller.error ?? 'Pairing failed.';
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: const Text('Pair with a code'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Form(
            key: _form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Generate a code in the VIRA dashboard under Devices. '
                  'Each code works once and expires after ten minutes.',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _server,
                  keyboardType: TextInputType.url,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: 'Server URL',
                    hintText: 'http://192.168.1.20:8000',
                    prefixIcon: Icon(Icons.dns_outlined),
                  ),
                  validator: (value) => value == null || value.trim().isEmpty
                      ? 'Enter the server address'
                      : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _code,
                  textCapitalization: TextCapitalization.characters,
                  textInputAction: TextInputAction.next,
                  autofillHints: const [AutofillHints.oneTimeCode],
                  onChanged: _onCodeChanged,
                  decoration: const InputDecoration(
                    labelText: 'Pairing code',
                    hintText: 'ABCD2345',
                    prefixIcon: Icon(Icons.key_outlined),
                  ),
                  validator: (value) =>
                      PairingPayload.tryParse(value ?? '') == null
                      ? 'Enter the 8-character pairing code or pairing link'
                      : null,
                ),
                if (_canScan) ...[
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      onPressed: _busy ? null : _scan,
                      icon: const Icon(Icons.qr_code_scanner),
                      label: const Text('Scan QR instead'),
                    ),
                  ),
                ],
                const SizedBox(height: 4),
                TextFormField(
                  controller: _deviceName,
                  textInputAction: TextInputAction.done,
                  onFieldSubmitted: (_) {
                    if (!_busy) _submit();
                  },
                  decoration: const InputDecoration(
                    labelText: 'Device name',
                    prefixIcon: Icon(Icons.devices_other_outlined),
                  ),
                  validator: (value) => value == null || value.trim().isEmpty
                      ? 'Name this device'
                      : null,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _error!,
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                ],
                const SizedBox(height: 8),
                Text(
                  'On Linux, paste the code above or the full pairing link '
                  'copied from the dashboard.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? 'Pairing…' : 'Pair device'),
        ),
      ],
    );
  }
}

class _QrScannerPage extends StatefulWidget {
  const _QrScannerPage();

  @override
  State<_QrScannerPage> createState() => _QrScannerPageState();
}

class _QrScannerPageState extends State<_QrScannerPage> {
  bool _handled = false;

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    for (final barcode in capture.barcodes) {
      final value = barcode.rawValue;
      if (value != null && value.trim().isNotEmpty) {
        _handled = true;
        Navigator.of(context).pop(value);
        return;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan pairing QR')),
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(onDetect: _onDetect),
          Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              margin: const EdgeInsets.all(24),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.65),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Text(
                'Point the camera at the QR code in the VIRA dashboard.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.white),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
