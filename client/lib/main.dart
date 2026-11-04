import 'package:flutter/material.dart';

import 'local_replica.dart';
import 'vira_api.dart';

void main() => runApp(const ViraApp());

class ViraApp extends StatelessWidget {
  const ViraApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'VIRA',
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
      useMaterial3: true,
    ),
    home: const ConnectionPage(),
  );
}

class ConnectionPage extends StatefulWidget {
  const ConnectionPage({super.key});
  @override
  State<ConnectionPage> createState() => _ConnectionPageState();
}

class _ConnectionPageState extends State<ConnectionPage> {
  final _server = TextEditingController(text: 'http://localhost:8000');
  final _username = TextEditingController();
  final _password = TextEditingController();
  String? _error;
  bool _busy = false;

  Future<void> _connect() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final api = ViraApi(_server.text.trim());
      await api.restoreSession();
      if (_username.text.trim().isEmpty && _password.text.isEmpty) {
        await api.currentUser();
      } else {
        await api.login(_username.text.trim(), _password.text);
      }
      if (api.deviceId == null) {
        await api.registerDevice(
          displayName: 'VIRA Flutter client',
          platform: 'other',
          deviceType: 'phone',
        );
      }
      if (!mounted) return;
      Navigator.of(
        context,
      ).pushReplacement(MaterialPageRoute(builder: (_) => HomePage(api: api)));
    } on Object catch (error) {
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('VIRA', style: Theme.of(context).textTheme.headlineMedium),
              const SizedBox(height: 8),
              const Text('Connect to your private VIRA server.'),
              const SizedBox(height: 24),
              TextField(
                controller: _server,
                decoration: const InputDecoration(labelText: 'Server URL'),
              ),
              TextField(
                controller: _username,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
              TextField(
                controller: _password,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Password'),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    _error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: _busy ? null : _connect,
                child: Text(_busy ? 'Connecting…' : 'Connect'),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _busy ? null : _showJoinHelp,
                icon: const Icon(Icons.qr_code_scanner),
                label: const Text('Join my family'),
              ),
              TextButton(
                onPressed: _busy ? null : _showSetupServer,
                child: const Text('Set up a new VIRA server'),
              ),
              TextButton(
                onPressed: _busy ? null : _showPasswordReset,
                child: const Text('Forgot password?'),
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Future<void> _showJoinHelp() => showDialog<void>(
    context: context,
    builder: (_) => const AlertDialog(
      title: Text('Join my family'),
      content: Text(
        'Ask the household administrator for the VIRA server address and your account credentials. '
        'QR pairing will be enabled when the server pairing service is configured.',
      ),
    ),
  );

  Future<void> _showSetupServer() async {
    final username = TextEditingController();
    final password = TextEditingController();
    final confirmation = TextEditingController();
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Set up VIRA server'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Use this only on a fresh server with no administrator.',
              ),
              TextField(
                controller: username,
                decoration: const InputDecoration(
                  labelText: 'Administrator username',
                ),
              ),
              TextField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Password'),
              ),
              TextField(
                controller: confirmation,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Confirm password',
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              try {
                final api = ViraApi(_server.text.trim());
                final response = await api.setupServer(
                  username.text.trim(),
                  password.text,
                  confirmation.text,
                );
                if (context.mounted) Navigator.pop(context, response);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Create administrator'),
          ),
        ],
      ),
    );
    username.dispose();
    password.dispose();
    confirmation.dispose();
    if (result != null && mounted) {
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Server is ready'),
          content: SelectableText(
            'Save this recovery code securely:\n\n${result['recovery_code'] ?? 'Not returned'}',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Done'),
            ),
          ],
        ),
      );
    }
  }

  Future<void> _showPasswordReset() async {
    final username = TextEditingController(text: _username.text);
    final recovery = TextEditingController();
    final password = TextEditingController();
    final confirmation = TextEditingController();
    final reset = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Reset password'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: username,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
              TextField(
                controller: recovery,
                decoration: const InputDecoration(labelText: 'Recovery code'),
              ),
              TextField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'New password'),
              ),
              TextField(
                controller: confirmation,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Confirm password',
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              try {
                await ViraApi(_server.text.trim()).resetPassword(
                  username.text.trim(),
                  recovery.text.trim(),
                  password.text,
                  confirmation.text,
                );
                if (context.mounted) Navigator.pop(context, true);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Reset password'),
          ),
        ],
      ),
    );
    username.dispose();
    recovery.dispose();
    password.dispose();
    confirmation.dispose();
    if (reset == true && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password reset. You can sign in now.')),
      );
    }
  }
}

enum WorkspacePage {
  dashboard,
  family,
  chat,
  agents,
  notes,
  lists,
  reminders,
  search,
  devices,
  diagnostics,
  privacy,
  settings,
  users,
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api});
  final ViraApi api;
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  WorkspacePage _page = WorkspacePage.dashboard;
  Map<String, dynamic>? _health;
  Map<String, dynamic>? _orchestration;
  Map<String, dynamic>? _workspace;
  List<Map<String, dynamic>> _agents = [];
  List<Map<String, dynamic>> _devices = [];
  List<Map<String, dynamic>> _users = [];
  List<Map<String, dynamic>> _notes = [];
  List<Map<String, dynamic>> _households = [];
  List<Map<String, dynamic>> _members = [];
  List<Map<String, dynamic>> _notebooks = [];
  List<Map<String, dynamic>> _reminders = [];
  List<Map<String, dynamic>> _checklistItems = [];
  String _syncState = 'Syncing';
  String _lastSync = 'Never';
  String? _loadError;
  bool _loading = true;
  final _chat = TextEditingController();
  String _answer = '';
  String? _username;
  bool _isAdmin = false;
  LocalReplica? _replica;

  @override
  void initState() {
    super.initState();
    LocalReplica.open().then((replica) {
      if (mounted) setState(() => _replica = replica);
    });
    _loadWorkspace();
  }

  Future<void> _loadWorkspace() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final user = await widget.api.currentUser();
      final roles = (user['roles'] as List? ?? []).map(
        (role) => role.toString(),
      );
      final isAdmin = roles.contains('admin');
      final results = isAdmin
          ? await Future.wait([
              widget.api.health(),
              widget.api.orchestration(),
              widget.api.agents(),
              widget.api.devices(),
              widget.api.users(),
            ])
          : <dynamic>[
              await widget.api.workspace(),
              null,
              <dynamic>[],
              <dynamic>[],
              <dynamic>[],
            ];
      final homes = await widget.api.households();
      if (homes.isNotEmpty) {
        widget.api.householdId = homes.first['id'] as String;
        await widget.api.flushPendingOps();
        final members = await widget.api.members(widget.api.householdId!);
        final notebooks = await widget.api.notebooks(widget.api.householdId!);
        final cursor = _replica?.cursor(widget.api.householdId!) ?? 0;
        final changes = await widget.api.changes(cursor: cursor);
        final byKey = <String, Map<String, dynamic>>{
          for (final entity
              in (_replica?.readEntities(widget.api.householdId!) ?? []))
            '${entity['entity_type']}:${entity['id']}': entity,
        };
        for (final change in changes) {
          final key = '${change['entity_type']}:${change['entity_id']}';
          if (change['op'] == 'delete') {
            byKey.remove(key);
          } else if (change['data'] is Map) {
            byKey[key] = {
              'entity_type': change['entity_type'],
              ...Map<String, dynamic>.from(change['data'] as Map),
            };
          }
        }
        if (_replica != null) {
          await _replica!.replaceEntities(
            widget.api.householdId!,
            byKey.values.toList(),
          );
          if (changes.isNotEmpty) {
            await _replica!.setCursor(
              widget.api.householdId!,
              changes.last['seq'] as int,
            );
          }
        }
        final entities = byKey.values.toList();
        _notes = entities
            .where((item) => item['entity_type'] == 'note')
            .map(Map<String, dynamic>.from)
            .toList();
        _checklistItems = entities
            .where((item) => item['entity_type'] == 'checklist_item')
            .map(Map<String, dynamic>.from)
            .toList();
        _reminders = entities
            .where((item) => item['entity_type'] == 'reminder')
            .map(Map<String, dynamic>.from)
            .toList();
        _members = members;
        _notebooks = notebooks;
        _syncState = 'Synced';
        _lastSync = DateTime.now().toLocal().toString().substring(0, 16);
      }
      if (!mounted) return;
      setState(() {
        _username = user['username']?.toString();
        _isAdmin = isAdmin;
        _health = results[0] as Map<String, dynamic>?;
        _orchestration = results[1] as Map<String, dynamic>?;
        _agents = isAdmin
            ? (((results[2] as Map<String, dynamic>)['loaded'] as List?) ?? [])
                  .map((item) => Map<String, dynamic>.from(item as Map))
                  .toList()
            : <Map<String, dynamic>>[];
        _workspace = isAdmin ? null : results[0] as Map<String, dynamic>;
        if (!isAdmin) {
          _health = _workspace?['server'] as Map<String, dynamic>?;
          _orchestration = {
            'scheduler': _workspace?['scheduler'] ?? {},
            'agents': _workspace?['agents'] ?? [],
          };
          _agents = (_workspace?['agents'] as List? ?? [])
              .map((item) => Map<String, dynamic>.from(item as Map))
              .toList();
        }
        _devices = (results[3] as List? ?? [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        _users = (results[4] as List? ?? [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        _households = homes;
        _loading = false;
      });
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _loading = false;
          _syncState = 'Needs attention';
          _loadError = error.toString();
        });
      }
    }
  }

  Future<void> _sendChat() async {
    if (_chat.text.trim().isEmpty) return;
    final message = _chat.text.trim();
    setState(() => _answer = 'Thinking…');
    try {
      final result = await widget.api.chat(message);
      setState(() {
        _answer = (result['response'] ?? result['message'] ?? '').toString();
        _chat.clear();
      });
    } on Object catch (error) {
      setState(() => _answer = 'Unable to reach VIRA: $error');
    }
  }

  Future<void> _logout() async {
    await widget.api.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const ConnectionPage()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(_title),
      actions: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Chip(
            avatar: Icon(
              _syncState == 'Synced'
                  ? Icons.cloud_done
                  : _syncState == 'Syncing'
                  ? Icons.sync
                  : Icons.cloud_off,
              size: 18,
            ),
            label: Text(_syncState),
          ),
        ),
        IconButton(
          tooltip: 'Refresh',
          onPressed: _loading ? null : _loadWorkspace,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    drawer: _drawer(context),
    body: _loading
        ? const Center(child: CircularProgressIndicator())
        : _loadError != null
        ? _errorView()
        : _content(),
  );

  String get _title => switch (_page) {
    WorkspacePage.dashboard => 'Dashboard',
    WorkspacePage.family => 'My Family',
    WorkspacePage.chat => 'Talk to Chatbot',
    WorkspacePage.agents => 'Running Agents',
    WorkspacePage.notes => 'Family Notes',
    WorkspacePage.lists => 'Checklists',
    WorkspacePage.reminders => 'Reminders',
    WorkspacePage.search => 'Search',
    WorkspacePage.devices => 'Devices',
    WorkspacePage.diagnostics => 'Diagnostics',
    WorkspacePage.privacy => 'Privacy',
    WorkspacePage.users => 'Users',
    WorkspacePage.settings => 'Settings',
  };

  Widget _drawer(BuildContext context) {
    final pages = <WorkspacePage>[
      WorkspacePage.dashboard,
      WorkspacePage.family,
      WorkspacePage.chat,
      WorkspacePage.agents,
      WorkspacePage.notes,
      WorkspacePage.lists,
      WorkspacePage.reminders,
      if (_isAdmin) WorkspacePage.devices,
      WorkspacePage.search,
      WorkspacePage.diagnostics,
      WorkspacePage.privacy,
      WorkspacePage.settings,
      if (_isAdmin) WorkspacePage.users,
    ];
    return NavigationDrawer(
      selectedIndex: pages.indexOf(_page),
      onDestinationSelected: (index) {
        setState(() => _page = pages[index]);
        Navigator.pop(context);
      },
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(28, 24, 16, 16),
          child: Text(
            'VIRA Workspace',
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ),
        if (_username != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(28, 0, 16, 16),
            child: Text('Signed in as $_username'),
          ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.dashboard_outlined),
          selectedIcon: Icon(Icons.dashboard),
          label: Text('Dashboard'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.home_outlined),
          selectedIcon: Icon(Icons.home),
          label: Text('My Family'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.chat_outlined),
          selectedIcon: Icon(Icons.chat),
          label: Text('Talk to Chatbot'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.smart_toy_outlined),
          selectedIcon: Icon(Icons.smart_toy),
          label: Text('Running Agents'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.notes_outlined),
          selectedIcon: Icon(Icons.notes),
          label: Text('Family Notes'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.checklist_outlined),
          selectedIcon: Icon(Icons.checklist),
          label: Text('Checklists'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.notifications_none),
          selectedIcon: Icon(Icons.notifications),
          label: Text('Reminders'),
        ),
        if (_isAdmin)
          const NavigationDrawerDestination(
            icon: Icon(Icons.devices_outlined),
            selectedIcon: Icon(Icons.devices),
            label: Text('Devices'),
          ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.search),
          label: Text('Search'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.network_check),
          label: Text('Diagnostics'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.privacy_tip_outlined),
          label: Text('Privacy'),
        ),
        const NavigationDrawerDestination(
          icon: Icon(Icons.settings_outlined),
          selectedIcon: Icon(Icons.settings),
          label: Text('Settings'),
        ),
        if (_isAdmin)
          const NavigationDrawerDestination(
            icon: Icon(Icons.group_outlined),
            selectedIcon: Icon(Icons.group),
            label: Text('Users'),
          ),
        const Divider(),
        ListTile(
          leading: const Icon(Icons.logout),
          title: const Text('Sign out'),
          onTap: _logout,
        ),
      ],
    );
  }

  Widget _content() => switch (_page) {
    WorkspacePage.dashboard => _dashboard(),
    WorkspacePage.family => _familyView(),
    WorkspacePage.chat => _chatView(),
    WorkspacePage.agents => _agentsView(),
    WorkspacePage.notes => _notesView(),
    WorkspacePage.lists => _listsView(),
    WorkspacePage.reminders => _remindersView(),
    WorkspacePage.search => _searchView(),
    WorkspacePage.devices => _devicesView(),
    WorkspacePage.diagnostics => _diagnosticsView(),
    WorkspacePage.privacy => _privacyView(),
    WorkspacePage.users => _usersView(),
    WorkspacePage.settings => _settingsView(),
  };

  Widget _dashboard() {
    final scheduler = _orchestration?['scheduler'] as Map? ?? {};
    final tools = _orchestration?['tools'] as Map? ?? {};
    return RefreshIndicator(
      onRefresh: _loadWorkspace,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            'Welcome back${_username == null ? '' : ', $_username'}',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              _statCard(
                'Server',
                _health?['status'] ?? 'unknown',
                Icons.dns,
                Colors.green,
              ),
              _statCard(
                'Agents',
                '${_agents.length}',
                Icons.smart_toy,
                Colors.indigo,
              ),
              _statCard(
                'Running tasks',
                '${scheduler['running_tasks'] ?? 0}',
                Icons.autorenew,
                Colors.orange,
              ),
              _statCard(
                'Tools',
                '${tools['total'] ?? 0}',
                Icons.build,
                Colors.teal,
              ),
            ],
          ),
          const SizedBox(height: 24),
          Card(
            child: ListTile(
              leading: const Icon(Icons.chat),
              title: const Text('Talk to VIRA'),
              subtitle: const Text(
                'Ask questions and run tasks with your assistant.',
              ),
              trailing: const Icon(Icons.arrow_forward),
              onTap: () => setState(() => _page = WorkspacePage.chat),
            ),
          ),
          Card(
            child: ListTile(
              leading: const Icon(Icons.smart_toy),
              title: const Text('View running agents'),
              subtitle: Text('${_agents.length} agents are available'),
              trailing: const Icon(Icons.arrow_forward),
              onTap: () => setState(() => _page = WorkspacePage.agents),
            ),
          ),
          Card(
            child: ListTile(
              leading: const Icon(Icons.home),
              title: Text(
                _households.isEmpty
                    ? 'Set up your family space'
                    : _households.first['name']?.toString() ?? 'My family',
              ),
              subtitle: Text(
                '${_members.length} members · ${_notebooks.length} notebooks',
              ),
              trailing: const Icon(Icons.arrow_forward),
              onTap: () => setState(() => _page = WorkspacePage.family),
            ),
          ),
        ],
      ),
    );
  }

  Widget _familyView() {
    final household = _households.isEmpty ? null : _households.first;
    return RefreshIndicator(
      onRefresh: _loadWorkspace,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            household?['name']?.toString() ?? 'My family',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 4),
          Text(
            household == null
                ? 'Your shared VIRA space'
                : '${household['member_count'] ?? _members.length} people sharing this space',
          ),
          const SizedBox(height: 20),
          _sectionCard(
            title: 'Family members',
            icon: Icons.people,
            action: _isAdmin
                ? TextButton.icon(
                    onPressed: _showAddMember,
                    icon: const Icon(Icons.person_add),
                    label: const Text('Add'),
                  )
                : null,
            child: _members.isEmpty
                ? const Text('No members found.')
                : Column(
                    children: _members
                        .map(
                          (member) => ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: CircleAvatar(
                              child: Text(
                                (member['username']?.toString() ?? '?')[0]
                                    .toUpperCase(),
                              ),
                            ),
                            title: Text(
                              member['username']?.toString() ?? 'Member',
                            ),
                            subtitle: Text(member['role']?.toString() ?? ''),
                            trailing: _isAdmin
                                ? PopupMenuButton<String>(
                                    onSelected: (role) => _changeMemberRole(
                                      member['public_id'].toString(),
                                      role,
                                    ),
                                    itemBuilder: (_) => const [
                                      PopupMenuItem(
                                        value: 'admin',
                                        child: Text('Administrator'),
                                      ),
                                      PopupMenuItem(
                                        value: 'adult',
                                        child: Text('Adult'),
                                      ),
                                      PopupMenuItem(
                                        value: 'child',
                                        child: Text('Child'),
                                      ),
                                      PopupMenuItem(
                                        value: 'guest',
                                        child: Text('Guest'),
                                      ),
                                    ],
                                  )
                                : null,
                          ),
                        )
                        .toList(),
                  ),
          ),
          _sectionCard(
            title: 'Notebooks',
            icon: Icons.menu_book,
            child: _notebooks.isEmpty
                ? const Text('Your family notebook will appear here.')
                : Column(
                    children: _notebooks
                        .map(
                          (book) => ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.book_outlined),
                            title: Text(
                              book['title']?.toString() ?? 'Notebook',
                            ),
                            subtitle: Text(
                              book['visibility']?.toString() ?? 'household',
                            ),
                          ),
                        )
                        .toList(),
                  ),
          ),
          _sectionCard(
            title: 'Upcoming reminders',
            icon: Icons.notifications_active,
            child: _reminders.isEmpty
                ? const Text('No reminders yet.')
                : Column(
                    children: _reminders
                        .map(
                          (reminder) => ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: Icon(
                              reminder['urgent'] == true
                                  ? Icons.priority_high
                                  : Icons.notifications_none,
                            ),
                            title: Text(
                              reminder['title']?.toString() ?? 'Reminder',
                            ),
                            subtitle: Text(
                              reminder['due_at']?.toString() ?? 'No due date',
                            ),
                          ),
                        )
                        .toList(),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _sectionCard({
    required String title,
    required IconData icon,
    required Widget child,
    Widget? action,
  }) => Card(
    child: Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(icon),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              ?action,
            ],
          ),
          const Divider(),
          child,
        ],
      ),
    ),
  );

  Widget _statCard(String label, String value, IconData icon, Color color) =>
      SizedBox(
        width: 220,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                CircleAvatar(
                  backgroundColor: color.withAlpha(30),
                  foregroundColor: color,
                  child: Icon(icon),
                ),
                const SizedBox(width: 12),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label),
                    Text(value, style: Theme.of(context).textTheme.titleLarge),
                  ],
                ),
              ],
            ),
          ),
        ),
      );

  Widget _agentsView() {
    if (_agents.isEmpty) {
      return const Center(child: Text('No agents are currently loaded.'));
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _agents.length,
      itemBuilder: (_, index) {
        final agent = _agents[index];
        return Card(
          child: ListTile(
            leading: Icon(
              agent['enabled'] == false
                  ? Icons.pause_circle_outline
                  : Icons.smart_toy,
            ),
            title: Text(
              agent['name']?.toString() ??
                  agent['agent_id']?.toString() ??
                  'Agent',
            ),
            subtitle: Text(
              agent['description']?.toString() ?? 'No description',
            ),
            trailing: Chip(
              label: Text(
                agent['state']?.toString() ??
                    (agent['enabled'] == false ? 'disabled' : 'loaded'),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _devicesView() => _devices.isEmpty
      ? const Center(child: Text('No paired devices found.'))
      : ListView.builder(
          padding: const EdgeInsets.all(16),
          itemCount: _devices.length,
          itemBuilder: (_, index) {
            final device = _devices[index];
            return Card(
              child: ListTile(
                leading: const Icon(Icons.devices),
                title: Text(device['display_name']?.toString() ?? 'Device'),
                subtitle: Text(
                  '${device['platform'] ?? 'unknown'} · ${device['status'] ?? 'unknown'}',
                ),
                trailing: PopupMenuButton<String>(
                  onSelected: (action) async {
                    if (action == 'rename') {
                      await _renameDevice(device);
                    } else if (action == 'revoke') {
                      await widget.api.revokeDevice(
                        (device['device_id'] ?? device['id']).toString(),
                      );
                      await _loadWorkspace();
                    }
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'rename', child: Text('Rename')),
                    PopupMenuItem(
                      value: 'revoke',
                      child: Text('Revoke access'),
                    ),
                  ],
                ),
              ),
            );
          },
        );

  Future<void> _renameDevice(Map<String, dynamic> device) async {
    final controller = TextEditingController(
      text: device['display_name']?.toString() ?? '',
    );
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename device'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Device name'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (controller.text.trim().isEmpty) return;
              try {
                await widget.api.renameDevice(
                  (device['device_id'] ?? device['id']).toString(),
                  controller.text.trim(),
                );
                if (context.mounted) Navigator.pop(context, true);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (saved == true && mounted) await _loadWorkspace();
  }

  Widget _usersView() => Padding(
    padding: const EdgeInsets.all(16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Server users',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
            FilledButton.icon(
              onPressed: _showCreateUser,
              icon: const Icon(Icons.person_add),
              label: const Text('Add user'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Expanded(
          child: _users.isEmpty
              ? const Center(child: Text('No users found.'))
              : ListView.builder(
                  itemCount: _users.length,
                  itemBuilder: (_, index) {
                    final user = _users[index];
                    final active = user['status'] == 'active';
                    return Card(
                      child: ListTile(
                        leading: CircleAvatar(
                          child: Text(
                            (user['username']?.toString() ?? '?')[0]
                                .toUpperCase(),
                          ),
                        ),
                        title: Text(user['username']?.toString() ?? 'User'),
                        subtitle: Text(
                          '${user['role'] ?? 'user'} · ${user['status'] ?? 'unknown'}',
                        ),
                        trailing: PopupMenuButton<String>(
                          onSelected: (value) async {
                            await widget.api.updateUser(
                              user['user_id'].toString(),
                              status: value,
                            );
                            await _loadWorkspace();
                          },
                          itemBuilder: (_) => [
                            PopupMenuItem(
                              value: active ? 'disabled' : 'active',
                              child: Text(active ? 'Disable' : 'Enable'),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    ),
  );

  Future<void> _showCreateUser() async {
    final username = TextEditingController();
    final password = TextEditingController();
    var role = 'user';
    final created = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Add VIRA user'),
          content: SizedBox(
            width: 400,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: username,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: 'Name or username',
                    hintText: 'mom, father, son',
                  ),
                ),
                DropdownButtonFormField<String>(
                  initialValue: role,
                  decoration: const InputDecoration(labelText: 'Role'),
                  items: const [
                    DropdownMenuItem(value: 'user', child: Text('User')),
                    DropdownMenuItem(
                      value: 'admin',
                      child: Text('Administrator'),
                    ),
                  ],
                  onChanged: (value) =>
                      setDialogState(() => role = value ?? 'user'),
                ),
                TextField(
                  controller: password,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Password (optional)',
                    helperText: 'Leave blank to generate a temporary password.',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                try {
                  final result = await widget.api.createUser(
                    username: username.text.trim(),
                    role: role,
                    password: password.text,
                  );
                  if (context.mounted) Navigator.pop(context, result);
                } on Object catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(
                      context,
                    ).showSnackBar(SnackBar(content: Text(error.toString())));
                  }
                }
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
    username.dispose();
    password.dispose();
    if (created == null || !mounted) return;
    await _loadWorkspace();
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('User created'),
        content: SelectableText(
          'Username: ${created['username']}\n'
          'Password: ${created['temporary_password'] ?? 'The password you entered'}\n'
          'Recovery code: ${created['recovery_code'] ?? 'Not returned'}\n\n'
          'Save these credentials now. They are shown only once.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Done'),
          ),
        ],
      ),
    );
  }

  Future<void> _showAddMember() async {
    final username = TextEditingController();
    final password = TextEditingController();
    var role = 'adult';
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Add family member'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: username,
                autofocus: true,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
              TextField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Password',
                  helperText: 'Leave blank to generate one-time credentials.',
                ),
              ),
              DropdownButtonFormField<String>(
                initialValue: role,
                decoration: const InputDecoration(labelText: 'Family role'),
                items: const [
                  DropdownMenuItem(value: 'adult', child: Text('Adult')),
                  DropdownMenuItem(value: 'child', child: Text('Child')),
                  DropdownMenuItem(value: 'guest', child: Text('Guest')),
                ],
                onChanged: (value) =>
                    setDialogState(() => role = value ?? 'adult'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                try {
                  final created = await widget.api.createUser(
                    username: username.text.trim(),
                    role: 'user',
                    password: password.text,
                  );
                  await _loadWorkspace();
                  final member = _members
                      .cast<Map<String, dynamic>?>()
                      .firstWhere(
                        (item) => item?['username'] == username.text.trim(),
                        orElse: () => null,
                      );
                  if (member != null) {
                    await _changeMemberRole(
                      member['public_id'].toString(),
                      role,
                      refresh: false,
                    );
                  }
                  if (context.mounted) Navigator.pop(context, created);
                } on Object catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(
                      context,
                    ).showSnackBar(SnackBar(content: Text(error.toString())));
                  }
                }
              },
              child: const Text('Add member'),
            ),
          ],
        ),
      ),
    );
    username.dispose();
    password.dispose();
    if (result != null && mounted) {
      final passwordText =
          result['temporary_password']?.toString() ??
          'Use the password you entered';
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Member added'),
          content: SelectableText(
            'Username: ${result['username']}\nPassword: $passwordText\n\n'
            'Share these credentials securely.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Done'),
            ),
          ],
        ),
      );
    }
  }

  Future<void> _changeMemberRole(
    String memberId,
    String role, {
    bool refresh = true,
  }) async {
    try {
      await widget.api.updateMember(widget.api.householdId!, memberId, role);
      if (refresh) await _loadWorkspace();
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.toString())));
      }
    }
  }

  Widget _listsView() {
    final checklists = _notes
        .where((note) => note['kind'] == 'checklist')
        .toList();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Shared lists',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
            FilledButton.icon(
              onPressed: _showAddChecklist,
              icon: const Icon(Icons.add),
              label: const Text('New list'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (checklists.isEmpty)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(20),
              child: Text(
                'Create a grocery, packing, or chores list for your family.',
              ),
            ),
          ),
        ...checklists.map(
          (list) => Card(
            child: ExpansionTile(
              leading: const Icon(Icons.checklist),
              title: Text(list['title']?.toString() ?? 'Checklist'),
              subtitle: Text(
                '${_checklistItems.where((item) => item['note_id'] == list['id']).length} items',
              ),
              children: [
                ..._checklistItems
                    .where((item) => item['note_id'] == list['id'])
                    .map(
                      (item) => CheckboxListTile(
                        value: item['done'] == true || item['done'] == 1,
                        title: Text(item['text']?.toString() ?? ''),
                        onChanged: (done) =>
                            _toggleChecklistItem(item, done ?? false),
                      ),
                    ),
                ListTile(
                  leading: const Icon(Icons.add),
                  title: const Text('Add item'),
                  onTap: () => _showAddChecklistItem(list['id'].toString()),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _showAddChecklist() async {
    final title = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New checklist'),
        content: TextField(
          controller: title,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'List name',
            hintText: 'Groceries, Packing, Chores',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (title.text.trim().isEmpty) return;
              try {
                await widget.api.saveNote(
                  'list-${DateTime.now().microsecondsSinceEpoch}',
                  title.text.trim(),
                  '',
                  kind: 'checklist',
                );
                if (context.mounted) Navigator.pop(context, true);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Create'),
          ),
        ],
      ),
    );
    title.dispose();
    if (result == true && mounted) await _loadWorkspace();
  }

  Future<void> _showAddChecklistItem(String noteId) async {
    final text = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add list item'),
        content: TextField(
          controller: text,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Item'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (text.text.trim().isEmpty) return;
              try {
                await widget.api.saveChecklistItem(
                  id: 'item-${DateTime.now().microsecondsSinceEpoch}',
                  noteId: noteId,
                  text: text.text.trim(),
                  done: false,
                );
                if (context.mounted) Navigator.pop(context, true);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Add'),
          ),
        ],
      ),
    );
    text.dispose();
    if (result == true && mounted) await _loadWorkspace();
  }

  Future<void> _toggleChecklistItem(
    Map<String, dynamic> item,
    bool done,
  ) async {
    try {
      await widget.api.saveChecklistItem(
        id: item['id'].toString(),
        noteId: item['note_id'].toString(),
        text: item['text']?.toString() ?? '',
        done: done,
      );
      await _loadWorkspace();
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.toString())));
      }
    }
  }

  Widget _remindersView() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              'Reminders',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
          ),
          FilledButton.icon(
            onPressed: _showAddReminder,
            icon: const Icon(Icons.add_alert),
            label: const Text('New reminder'),
          ),
        ],
      ),
      const SizedBox(height: 12),
      if (_reminders.isEmpty)
        const Card(
          child: Padding(
            padding: EdgeInsets.all(20),
            child: Text(
              'Create reminders for everyone or a specific family member.',
            ),
          ),
        ),
      ..._reminders.map(
        (reminder) => Card(
          child: ListTile(
            leading: Icon(
              reminder['urgent'] == true
                  ? Icons.priority_high
                  : Icons.notifications_active_outlined,
            ),
            title: Text(reminder['title']?.toString() ?? 'Reminder'),
            subtitle: Text(
              '${reminder['due_at'] ?? 'No due date'} · ${reminder['status'] ?? 'active'}',
            ),
            trailing: const Icon(Icons.chevron_right),
          ),
        ),
      ),
    ],
  );

  Future<void> _showAddReminder() async {
    final title = TextEditingController();
    final due = TextEditingController(
      text: DateTime.now().add(const Duration(hours: 1)).toIso8601String(),
    );
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New reminder'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: title,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Reminder'),
            ),
            TextField(
              controller: due,
              decoration: const InputDecoration(
                labelText: 'Due time',
                helperText:
                    'Use UTC ISO-8601, for example 2026-11-04T10:00:00Z',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (title.text.trim().isEmpty) return;
              try {
                await widget.api.saveReminder(
                  id: 'reminder-${DateTime.now().microsecondsSinceEpoch}',
                  title: title.text.trim(),
                  dueAt: due.text.trim(),
                );
                if (context.mounted) Navigator.pop(context, true);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    title.dispose();
    due.dispose();
    if (result == true && mounted) await _loadWorkspace();
  }

  Widget _searchView() {
    final query = TextEditingController();
    return StatefulBuilder(
      builder: (context, setSearchState) {
        final value = query.text.trim().toLowerCase();
        final matches = _notes
            .where(
              (note) =>
                  value.isEmpty ||
                  '${note['title']} ${note['body_md']}'.toLowerCase().contains(
                    value,
                  ),
            )
            .toList();
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              TextField(
                controller: query,
                autofocus: true,
                onChanged: (_) => setSearchState(() {}),
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  labelText: 'Search notes and lists',
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: ListView(
                  children: matches
                      .map(
                        (note) => Card(
                          child: ListTile(
                            leading: const Icon(Icons.search),
                            title: Text(note['title']?.toString() ?? ''),
                            subtitle: Text(note['body_md']?.toString() ?? ''),
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _notesView() => Padding(
    padding: const EdgeInsets.all(16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Shared notes',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
            FilledButton.icon(
              onPressed: _showAddNote,
              icon: const Icon(Icons.add),
              label: const Text('New note'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Expanded(
          child: _notes.isEmpty
              ? const Center(
                  child: Text('No shared notes yet. Create the first one.'),
                )
              : ListView.builder(
                  itemCount: _notes.length,
                  itemBuilder: (_, index) {
                    final note = _notes[index];
                    return Card(
                      child: ListTile(
                        leading: Icon(
                          note['pinned'] == true
                              ? Icons.push_pin
                              : Icons.note_outlined,
                        ),
                        title: Text(note['title']?.toString() ?? 'Untitled'),
                        subtitle: Text(
                          note['body_md']?.toString() ?? '',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    ),
  );

  Future<void> _showAddNote() async {
    final title = TextEditingController();
    final body = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New family note'),
        content: SizedBox(
          width: 460,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: title,
                autofocus: true,
                decoration: const InputDecoration(labelText: 'Title'),
              ),
              TextField(
                controller: body,
                minLines: 3,
                maxLines: 7,
                decoration: const InputDecoration(labelText: 'Note'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (title.text.trim().isEmpty) return;
              try {
                await widget.api.saveNote(
                  'note-${DateTime.now().microsecondsSinceEpoch}',
                  title.text.trim(),
                  body.text.trim(),
                );
                if (context.mounted) Navigator.pop(context, true);
              } on Object catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(error.toString())));
                }
              }
            },
            child: const Text('Save note'),
          ),
        ],
      ),
    );
    title.dispose();
    body.dispose();
    if (result == true && mounted) await _loadWorkspace();
  }

  Widget _chatView() => Padding(
    padding: const EdgeInsets.all(16),
    child: Column(
      children: [
        Expanded(
          child: SingleChildScrollView(
            child: Align(
              alignment: Alignment.topLeft,
              child: Text(_answer.isEmpty ? 'Ask VIRA something.' : _answer),
            ),
          ),
        ),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _chat,
                onSubmitted: (_) => _sendChat(),
                decoration: const InputDecoration(hintText: 'Message VIRA'),
              ),
            ),
            IconButton(onPressed: _sendChat, icon: const Icon(Icons.send)),
          ],
        ),
      ],
    ),
  );

  Widget _diagnosticsView() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Text(
        'Connection diagnostics',
        style: Theme.of(context).textTheme.headlineSmall,
      ),
      const SizedBox(height: 12),
      Card(
        child: ListTile(
          leading: Icon(
            _syncState == 'Synced' ? Icons.check_circle : Icons.cloud_off,
            color: _syncState == 'Synced' ? Colors.green : Colors.orange,
          ),
          title: Text('Sync status: $_syncState'),
          subtitle: Text('Last successful sync: $_lastSync'),
          trailing: IconButton(
            tooltip: 'Test connection',
            onPressed: _loadWorkspace,
            icon: const Icon(Icons.refresh),
          ),
        ),
      ),
      Card(
        child: ListTile(
          leading: const Icon(Icons.link),
          title: const Text('Active server endpoint'),
          subtitle: Text(widget.api.baseUrl),
        ),
      ),
      Card(
        child: ListTile(
          leading: const Icon(Icons.home),
          title: const Text('Active household'),
          subtitle: Text(widget.api.householdId ?? 'Not selected'),
        ),
      ),
      const Card(
        child: ListTile(
          leading: Icon(Icons.security),
          title: Text('Transport security'),
          subtitle: Text(
            'Use HTTPS, a VPN, or a trusted LAN. Certificate pinning is pending server pairing support.',
          ),
        ),
      ),
    ],
  );

  Widget _privacyView() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Text(
        'Privacy and data',
        style: Theme.of(context).textTheme.headlineSmall,
      ),
      const SizedBox(height: 8),
      const Text(
        'VIRA keeps your family data on your configured server. Optional signals are disabled by default.',
      ),
      const SizedBox(height: 12),
      const Card(
        child: Column(
          children: [
            ListTile(
              leading: Icon(Icons.note),
              title: Text('Notes, lists, and reminders'),
              subtitle: Text('Sent to your family VIRA server when you sync.'),
            ),
            ListTile(
              leading: Icon(Icons.chat),
              title: Text('Chat messages'),
              subtitle: Text(
                'Sent to VIRA and the model provider configured by the server.',
              ),
            ),
            ListTile(
              leading: Icon(Icons.block),
              title: Text('Never collected'),
              subtitle: Text(
                'Contacts, advertising IDs, screenshots, keystrokes, and location.',
              ),
            ),
          ],
        ),
      ),
      SwitchListTile(
        value: false,
        onChanged: null,
        title: const Text('Location and calendar signals'),
        subtitle: const Text('Disabled and unavailable in this client build.'),
      ),
      ListTile(
        leading: const Icon(Icons.download),
        title: const Text('Export local workspace'),
        subtitle: const Text(
          'Export support will be enabled with the local database.',
        ),
        onTap: () => _showInfo(
          'Export',
          'Local export is planned for the next client storage milestone.',
        ),
      ),
      ListTile(
        leading: const Icon(Icons.delete_forever),
        title: const Text('Delete server data'),
        subtitle: const Text(
          'Requires an explicit server-side account workflow.',
        ),
        onTap: () => _showInfo(
          'Account deletion',
          'Ask the household administrator to remove this account.',
        ),
      ),
    ],
  );

  Future<void> _showInfo(String title, String message) => showDialog<void>(
    context: context,
    builder: (_) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    ),
  );

  Widget _settingsView() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      const ListTile(
        leading: Icon(Icons.language),
        title: Text('Connected server'),
        subtitle: Text('VIRA local server'),
      ),
      ListTile(
        leading: const Icon(Icons.refresh),
        title: const Text('Refresh workspace data'),
        onTap: _loadWorkspace,
      ),
      ListTile(
        leading: const Icon(Icons.logout),
        title: const Text('Sign out'),
        onTap: _logout,
      ),
    ],
  );

  Widget _errorView() => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.cloud_off, size: 48),
          const SizedBox(height: 12),
          Text(
            'Could not load the VIRA workspace:\n$_loadError',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: _loadWorkspace, child: const Text('Retry')),
        ],
      ),
    ),
  );
}
