import 'package:material_ui/material_ui.dart';

import '../features/activity/activity_page.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/devices/devices_page.dart';
import '../features/settings/settings_page.dart';

class AppModule {
  const AppModule({
    required this.id,
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.builder,
  });

  final String id;
  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final WidgetBuilder builder;
}

/// The navigation shell is generated from this list. Add a module here to add
/// a feature; remove it here and its page is no longer reachable.
const appModules = <AppModule>[
  AppModule(
    id: 'dashboard',
    label: 'Overview',
    icon: Icons.space_dashboard_outlined,
    selectedIcon: Icons.space_dashboard,
    builder: _dashboard,
  ),
  AppModule(
    id: 'activity',
    label: 'Activity',
    icon: Icons.bolt_outlined,
    selectedIcon: Icons.bolt,
    builder: _activity,
  ),
  AppModule(
    id: 'devices',
    label: 'Devices',
    icon: Icons.devices_other_outlined,
    selectedIcon: Icons.devices_other,
    builder: _devices,
  ),
  AppModule(
    id: 'settings',
    label: 'Settings',
    icon: Icons.settings_outlined,
    selectedIcon: Icons.settings,
    builder: _settings,
  ),
];

Widget _dashboard(BuildContext context) => const DashboardPage();
Widget _activity(BuildContext context) => const ActivityPage();
Widget _devices(BuildContext context) => const DevicesPage();
Widget _settings(BuildContext context) => const SettingsPage();
