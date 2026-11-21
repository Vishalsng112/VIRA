import 'package:material_ui/material_ui.dart';

import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../core/models/agent_inbox.dart';
import '../../data/api/vira_api.dart';

const _timezones = [
  'UTC',
  'Asia/Kolkata',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
];

const _weekdays = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

class ScheduleEditorPage extends StatefulWidget {
  const ScheduleEditorPage({super.key, this.recipe, this.existing});

  final AgentRecipe? recipe;
  final AgentSchedule? existing;

  @override
  State<ScheduleEditorPage> createState() => _ScheduleEditorPageState();
}

class _ScheduleEditorPageState extends State<ScheduleEditorPage> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _message;
  late final TextEditingController _interval;
  String _scheduleType = 'daily';
  TimeOfDay _time = const TimeOfDay(hour: 8, minute: 0);
  int _weekday = 0;
  String _timezone = 'UTC';
  bool _quietHours = false;
  TimeOfDay _quietStart = const TimeOfDay(hour: 22, minute: 0);
  TimeOfDay _quietEnd = const TimeOfDay(hour: 7, minute: 0);
  bool _webhook = false;
  String? _mode;
  bool _saving = false;
  bool get _editing => widget.existing != null;

  ViraApi? get _api => AppScope.of(context, listen: false).api;

  @override
  void initState() {
    super.initState();
    final recipe = widget.recipe;
    final existing = widget.existing;
    final defaults = recipe?.defaultSchedule ?? const <String, dynamic>{};
    _name = TextEditingController(
      text: existing?.name ?? recipe?.name ?? 'Daily agent',
    );
    _message = TextEditingController(
      text:
          existing?.message ??
          'Generate today\'s update from my available context.',
    );
    _interval = TextEditingController(
      text: (existing?.intervalMinutes ?? 60).toString(),
    );
    if (existing != null) {
      _scheduleType = existing.scheduleType;
      _time = _parseTime(existing.timeOfDay) ?? _time;
      _weekday = existing.weekday ?? 0;
      _timezone = _timezones.contains(existing.timezone)
          ? existing.timezone
          : 'UTC';
      _quietHours =
          existing.quietHoursStart != null && existing.quietHoursEnd != null;
      _quietStart = _parseTime(existing.quietHoursStart) ?? _quietStart;
      _quietEnd = _parseTime(existing.quietHoursEnd) ?? _quietEnd;
      _webhook = existing.channels.contains('webhook');
      _mode = existing.input['mode']?.toString();
    } else {
      _scheduleType = defaults['schedule_type']?.toString() ?? 'daily';
      _time = _parseTime(defaults['time_of_day']?.toString()) ?? _time;
      _weekday = defaults['weekday'] is num
          ? (defaults['weekday'] as num).toInt()
          : 0;
      final defaultZone = defaults['timezone']?.toString();
      if (defaultZone != null && _timezones.contains(defaultZone)) {
        _timezone = defaultZone;
      }
      final input = defaults['input'];
      if (input is Map) {
        _mode = input['mode']?.toString();
      }
      _mode ??= recipe?.defaultMode;
    }
    if (_mode == null && recipe != null && recipe.scheduleModes.isNotEmpty) {
      _mode = recipe.scheduleModes.first;
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _message.dispose();
    _interval.dispose();
    super.dispose();
  }

  TimeOfDay? _parseTime(String? value) {
    if (value == null) return null;
    final parts = value.split(':');
    if (parts.length != 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null) return null;
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
    return TimeOfDay(hour: hour, minute: minute);
  }

  String _formatTime(TimeOfDay value) =>
      '${value.hour.toString().padLeft(2, '0')}:'
      '${value.minute.toString().padLeft(2, '0')}';

  Future<void> _pickTime({required bool quiet, required bool start}) async {
    final picked = await showTimePicker(
      context: context,
      initialTime: quiet ? (start ? _quietStart : _quietEnd) : _time,
    );
    if (picked == null || !mounted) return;
    setState(() {
      if (quiet) {
        if (start) {
          _quietStart = picked;
        } else {
          _quietEnd = picked;
        }
      } else {
        _time = picked;
      }
    });
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    final api = _api;
    if (api == null) return;
    final agentId = widget.existing?.agentId ?? widget.recipe?.agentId ?? '';
    if (agentId.isEmpty) return;
    final input = <String, dynamic>{
      ...?widget.existing?.input,
      if (_mode != null && _mode!.isNotEmpty) 'mode': _mode,
    };
    final channels = <String>['inapp', if (_webhook) 'webhook'];
    setState(() => _saving = true);
    try {
      if (_editing) {
        await api.updateAgentSchedule(widget.existing!.id, {
          'name': _name.text.trim(),
          'message': _message.text.trim(),
          'schedule_type': _scheduleType,
          'timezone': _timezone,
          'time_of_day': _scheduleType == 'interval'
              ? null
              : _formatTime(_time),
          'weekday': _scheduleType == 'weekly' ? _weekday : null,
          'interval_minutes': _scheduleType == 'interval'
              ? int.tryParse(_interval.text.trim()) ?? 60
              : null,
          'quiet_hours_start': _quietHours ? _formatTime(_quietStart) : null,
          'quiet_hours_end': _quietHours ? _formatTime(_quietEnd) : null,
          'channels': channels,
          'input': input,
        });
      } else {
        await api.createAgentSchedule(
          agentId: agentId,
          name: _name.text.trim(),
          message: _message.text.trim(),
          scheduleType: _scheduleType,
          timezone: _timezone,
          timeOfDay: _scheduleType == 'interval' ? null : _formatTime(_time),
          weekday: _scheduleType == 'weekly' ? _weekday : null,
          intervalMinutes: _scheduleType == 'interval'
              ? int.tryParse(_interval.text.trim()) ?? 60
              : null,
          quietHoursStart: _quietHours ? _formatTime(_quietStart) : null,
          quietHoursEnd: _quietHours ? _formatTime(_quietEnd) : null,
          channels: channels,
          input: input,
        );
      }
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ViraApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final recipe = widget.recipe;
    final modes = recipe?.scheduleModes ?? const <String>[];
    return Scaffold(
      appBar: AppBar(title: Text(_editing ? 'Edit schedule' : 'New schedule')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            if (recipe != null)
              GlassCard(
                padding: const EdgeInsets.all(16),
                radius: 18,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      recipe.name,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      recipe.pitch,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            if (recipe != null) const SizedBox(height: 16),
            TextFormField(
              controller: _name,
              decoration: const InputDecoration(
                labelText: 'Schedule name',
                border: OutlineInputBorder(),
              ),
              validator: (value) =>
                  (value ?? '').trim().isEmpty ? 'Enter a name' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _message,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Instruction to the agent',
                border: OutlineInputBorder(),
              ),
              validator: (value) =>
                  (value ?? '').trim().isEmpty ? 'Enter an instruction' : null,
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _scheduleType,
              decoration: const InputDecoration(
                labelText: 'Repeat',
                border: OutlineInputBorder(),
              ),
              items: const [
                DropdownMenuItem(value: 'daily', child: Text('Every day')),
                DropdownMenuItem(value: 'weekly', child: Text('Every week')),
                DropdownMenuItem(
                  value: 'interval',
                  child: Text('At an interval'),
                ),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _scheduleType = value);
              },
            ),
            const SizedBox(height: 12),
            if (_scheduleType == 'weekly')
              DropdownButtonFormField<int>(
                initialValue: _weekday,
                decoration: const InputDecoration(
                  labelText: 'Day',
                  border: OutlineInputBorder(),
                ),
                items: [
                  for (var index = 0; index < _weekdays.length; index++)
                    DropdownMenuItem(
                      value: index,
                      child: Text(_weekdays[index]),
                    ),
                ],
                onChanged: (value) {
                  if (value != null) setState(() => _weekday = value);
                },
              ),
            if (_scheduleType != 'interval') ...[
              if (_scheduleType == 'weekly') const SizedBox(height: 12),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.schedule),
                title: const Text('Time'),
                subtitle: Text(_formatTime(_time)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _pickTime(quiet: false, start: true),
              ),
            ] else
              TextFormField(
                controller: _interval,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Interval (minutes)',
                  border: OutlineInputBorder(),
                ),
                validator: (value) {
                  final parsed = int.tryParse((value ?? '').trim());
                  if (parsed == null || parsed < 1) {
                    return 'Enter a positive number of minutes';
                  }
                  return null;
                },
              ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _timezone,
              decoration: const InputDecoration(
                labelText: 'Timezone',
                border: OutlineInputBorder(),
              ),
              items: [
                for (final zone in _timezones)
                  DropdownMenuItem(value: zone, child: Text(zone)),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _timezone = value);
              },
            ),
            if (modes.isNotEmpty) ...[
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: modes.contains(_mode) ? _mode : modes.first,
                decoration: const InputDecoration(
                  labelText: 'Agent mode',
                  border: OutlineInputBorder(),
                ),
                items: [
                  for (final mode in modes)
                    DropdownMenuItem(value: mode, child: Text(mode)),
                ],
                onChanged: (value) => setState(() => _mode = value),
              ),
            ],
            const SizedBox(height: 8),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Quiet hours'),
              subtitle: const Text(
                'Move runs out of this window instead of dropping them.',
              ),
              value: _quietHours,
              onChanged: (value) => setState(() => _quietHours = value),
            ),
            if (_quietHours) ...[
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Quiet from'),
                subtitle: Text(_formatTime(_quietStart)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _pickTime(quiet: true, start: true),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Quiet until'),
                subtitle: Text(_formatTime(_quietEnd)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _pickTime(quiet: true, start: false),
              ),
            ],
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Also deliver by webhook'),
              subtitle: const Text(
                'In-app delivery is always on. Webhook needs server configuration.',
              ),
              value: _webhook,
              onChanged: (value) => setState(() => _webhook = value),
            ),
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Icon(_editing ? Icons.save : Icons.add_alarm),
              label: Text(_editing ? 'Save changes' : 'Create schedule'),
            ),
          ],
        ),
      ),
    );
  }
}
