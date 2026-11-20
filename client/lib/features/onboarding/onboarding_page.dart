import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../data/api/vira_api.dart';

class OnboardingPage extends StatefulWidget {
  const OnboardingPage({super.key});

  @override
  State<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends State<OnboardingPage> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _server;
  late final TextEditingController _username;
  final _password = TextEditingController();
  late final TextEditingController _deviceName;
  String? _localError;

  @override
  void initState() {
    super.initState();
    final controller = AppScope.of(context, listen: false);
    _server = TextEditingController(text: controller.serverUrl);
    _username = TextEditingController();
    _deviceName = TextEditingController(text: controller.suggestedDeviceName);
  }

  @override
  void dispose() {
    _server.dispose();
    _username.dispose();
    _password.dispose();
    _deviceName.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (!(_form.currentState?.validate() ?? false)) return;
    setState(() => _localError = null);
    final controller = AppScope.of(context, listen: false);
    await controller.connect(
      server: _server.text,
      username: _username.text,
      password: _password.text,
      deviceName: _deviceName.text,
    );
    if (mounted && !controller.isConnected) {
      setState(() => _localError = controller.error);
    }
  }

  Future<void> _showSetupServer() async {
    final username = TextEditingController();
    final password = TextEditingController();
    final confirmation = TextEditingController();
    String? error;
    String? recovery;
    var busy = false;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: const Text('Create a VIRA administrator'),
          content: SizedBox(
            width: 420,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Use this only on a fresh VIRA server that has no administrator yet.',
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: username,
                    decoration: const InputDecoration(labelText: 'Username'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: password,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: 'Password'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: confirmation,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Confirm password',
                    ),
                  ),
                  if (error != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(dialogContext).colorScheme.error,
                      ),
                    ),
                  ],
                  if (recovery != null) ...[
                    const SizedBox(height: 16),
                    const Text('Save this recovery code securely:'),
                    const SizedBox(height: 6),
                    SelectableText(
                      recovery!,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ],
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: busy ? null : () => Navigator.pop(dialogContext),
              child: const Text('Close'),
            ),
            FilledButton(
              onPressed: busy
                  ? null
                  : () async {
                      setDialogState(() {
                        busy = true;
                        error = null;
                      });
                      try {
                        final code = await AppScope.of(
                          dialogContext,
                          listen: false,
                        ).setupServer(
                          server: _server.text,
                          username: username.text,
                          password: password.text,
                          confirmation: confirmation.text,
                        );
                        setDialogState(() {
                          recovery = code;
                          busy = false;
                        });
                      } on ViraApiException catch (exception) {
                        setDialogState(() {
                          error = exception.message;
                          busy = false;
                        });
                      } on Object catch (exception) {
                        setDialogState(() {
                          error = exception.toString();
                          busy = false;
                        });
                      }
                    },
              child: Text(busy ? 'Creating…' : 'Create administrator'),
            ),
          ],
        ),
      ),
    );
    username.dispose();
    password.dispose();
    confirmation.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final theme = Theme.of(context);
    final busy = controller.state == AppConnectionState.connecting;
    final error = _localError ?? controller.error;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 980),
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final wide = constraints.maxWidth >= 780;
                  final form = _formCard(theme, busy, error);
                  if (!wide) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          children: [
                            const BrandMark(size: 46),
                            const SizedBox(width: 14),
                            Text(
                              'VIRA Link',
                              style: theme.textTheme.headlineMedium?.copyWith(
                                fontWeight: FontWeight.w700,
                                letterSpacing: -0.6,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 20),
                        form,
                      ],
                    );
                  }
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Expanded(child: _intro(theme)),
                      const SizedBox(width: 48),
                      Expanded(child: form),
                    ],
                  );
                },
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _intro(ThemeData theme) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const BrandMark(size: 64),
      const SizedBox(height: 24),
      Text(
        'VIRA Link',
        style: theme.textTheme.displaySmall?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: -1.2,
        ),
      ),
      const SizedBox(height: 12),
      Text(
        'The device companion for your private VIRA server.',
        style: theme.textTheme.titleMedium?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
      const SizedBox(height: 28),
      const _FeatureLine(
        icon: Icons.wifi_off_outlined,
        title: 'Works offline',
        text:
            'Events are stored on this device and sent when the server is reachable.',
      ),
      const _FeatureLine(
        icon: Icons.shield_outlined,
        title: 'Scoped credentials',
        text:
            'Each device gets its own revocable credential, separate from your account.',
      ),
      const _FeatureLine(
        icon: Icons.tune_outlined,
        title: 'Modular capture',
        text:
            'Enable only the signals you want to share. Every collector can be turned off.',
      ),
    ],
  );

  Widget _formCard(ThemeData theme, bool busy, String? error) => Card(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Form(
        key: _form,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Connect this device',
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Sign in with your VIRA account. This app will enroll the device and keep it linked.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 24),
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
                  ? 'Enter a server URL'
                  : null,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _username,
              textInputAction: TextInputAction.next,
              autofillHints: const [AutofillHints.username],
              decoration: const InputDecoration(
                labelText: 'Username',
                prefixIcon: Icon(Icons.person_outline),
              ),
              validator: (value) => value == null || value.trim().isEmpty
                  ? 'Enter your username'
                  : null,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _password,
              obscureText: true,
              autofillHints: const [AutofillHints.password],
              onFieldSubmitted: (_) {
                if (!busy) _connect();
              },
              decoration: const InputDecoration(
                labelText: 'Password',
                prefixIcon: Icon(Icons.lock_outline),
              ),
              validator: (value) =>
                  value == null || value.isEmpty ? 'Enter your password' : null,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _deviceName,
              textInputAction: TextInputAction.done,
              onFieldSubmitted: (_) {
                if (!busy) _connect();
              },
              decoration: const InputDecoration(
                labelText: 'Device name',
                helperText: 'Shown in the VIRA server dashboard',
                prefixIcon: Icon(Icons.devices_other_outlined),
              ),
              validator: (value) => value == null || value.trim().isEmpty
                  ? 'Name this device'
                  : null,
            ),
            if (error != null) ...[
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: theme.colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  error,
                  style: TextStyle(color: theme.colorScheme.onErrorContainer),
                ),
              ),
            ],
            const SizedBox(height: 22),
            FilledButton.icon(
              onPressed: busy ? null : _connect,
              icon: busy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.link),
              label: Text(busy ? 'Connecting…' : 'Connect this device'),
            ),
            const SizedBox(height: 10),
            TextButton(
              onPressed: busy ? null : _showSetupServer,
              child: const Text('Set up a new VIRA server'),
            ),
          ],
        ),
      ),
    ),
  );
}

class _FeatureLine extends StatelessWidget {
  const _FeatureLine({
    required this.icon,
    required this.title,
    required this.text,
  });

  final IconData icon;
  final String title;
  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, size: 20, color: theme.colorScheme.primary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
