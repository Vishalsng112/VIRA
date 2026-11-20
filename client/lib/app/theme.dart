import 'package:material_ui/material_ui.dart';

/// VIRA Link design tokens.
///
/// The interface uses an iOS-inspired "liquid glass" language: soft aurora
/// gradients, translucent frosted panels, generous radii and pill controls.
/// Keep colours and measures here so every page feels like one product.
abstract final class ViraPalette {
  static const indigo = Color(0xFF5B6CFF);
  static const violet = Color(0xFF9B6BFF);
  static const pink = Color(0xFFFF7AB6);
  static const cyan = Color(0xFF52D6E8);
  static const mint = Color(0xFF4ADE9B);
  static const amber = Color(0xFFFFB55C);

  static const lightGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFF7F8FF), Color(0xFFEEF1FF), Color(0xFFFFF3FA)],
  );

  static const darkGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF070A16), Color(0xFF0C1024), Color(0xFF14102C)],
  );

  /// Frosted panel fill.
  static Color glassFill(Brightness brightness) => brightness == Brightness.dark
      ? Colors.white.withValues(alpha: 0.07)
      : Colors.white.withValues(alpha: 0.62);

  /// Stronger fill used for floating navigation.
  static Color glassBar(Brightness brightness) => brightness == Brightness.dark
      ? const Color(0xFF11162B).withValues(alpha: 0.72)
      : Colors.white.withValues(alpha: 0.78);

  static Color glassStroke(Brightness brightness) =>
      brightness == Brightness.dark
      ? Colors.white.withValues(alpha: 0.14)
      : Colors.white.withValues(alpha: 0.88);

  static Color glassShadow(Brightness brightness) =>
      brightness == Brightness.dark
      ? Colors.black.withValues(alpha: 0.42)
      : const Color(0xFF4A5B8C).withValues(alpha: 0.14);
}

const _radius = 24.0;
const _pill = StadiumBorder();
const _seed = ViraPalette.indigo;

ThemeData buildLightTheme() => _theme(Brightness.light);

ThemeData buildDarkTheme() => _theme(Brightness.dark);

ThemeData _theme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: brightness)
      .copyWith(
        surface: dark ? const Color(0xFF0A0E1D) : const Color(0xFFF6F7FE),
        surfaceContainerLowest: dark ? const Color(0xFF0A0E1D) : Colors.white,
        surfaceContainerLow: dark
            ? const Color(0xFF11162B)
            : const Color(0xFFFDFDFF),
        surfaceContainer: dark
            ? const Color(0xFF151B33)
            : const Color(0xFFF1F3FC),
        surfaceContainerHigh: dark
            ? const Color(0xFF1B2240)
            : const Color(0xFFE9ECF9),
        surfaceContainerHighest: dark
            ? const Color(0xFF222A4A)
            : const Color(0xFFE2E6F5),
        primary: dark ? const Color(0xFF8E9BFF) : const Color(0xFF4A5BEF),
        secondary: ViraPalette.violet,
        tertiary: ViraPalette.pink,
        outlineVariant: dark
            ? const Color(0xFF2C3557)
            : const Color(0xFFE3E7F5),
      );
  final base = ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    fontFamily: null,
  );
  final text = base.textTheme.apply(
    bodyColor: scheme.onSurface,
    displayColor: scheme.onSurface,
  );
  return base.copyWith(
    scaffoldBackgroundColor: Colors.transparent,
    canvasColor: Colors.transparent,
    textTheme: text.copyWith(
      displaySmall: text.displaySmall?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -1.6,
      ),
      headlineMedium: text.headlineMedium?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -1.0,
      ),
      headlineSmall: text.headlineSmall?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -0.6,
      ),
      titleLarge: text.titleLarge?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -0.3,
      ),
      titleMedium: text.titleMedium?.copyWith(
        fontWeight: FontWeight.w600,
        letterSpacing: -0.2,
      ),
      bodyLarge: text.bodyLarge?.copyWith(height: 1.4),
      bodyMedium: text.bodyMedium?.copyWith(height: 1.45),
    ),
    splashFactory: InkSparkle.splashFactory,
    visualDensity: VisualDensity.standard,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.iOS: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.macOS: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.linux: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.windows: FadeForwardsPageTransitionsBuilder(),
      },
    ),
    appBarTheme: AppBarTheme(
      elevation: 0,
      scrolledUnderElevation: 0,
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      foregroundColor: scheme.onSurface,
      centerTitle: false,
      titleTextStyle: text.titleLarge?.copyWith(color: scheme.onSurface),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: ViraPalette.glassFill(brightness),
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_radius),
        side: BorderSide(color: ViraPalette.glassStroke(brightness)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark
          ? Colors.white.withValues(alpha: 0.06)
          : Colors.white.withValues(alpha: 0.72),
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      hintStyle: TextStyle(
        color: scheme.onSurfaceVariant.withValues(alpha: 0.7),
      ),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: ViraPalette.glassStroke(brightness)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: ViraPalette.glassStroke(brightness)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(
          color: scheme.primary.withValues(alpha: 0.8),
          width: 1.6,
        ),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: scheme.error, width: 1.2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, 50),
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
        shape: _pill,
        textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 13),
        shape: _pill,
        side: BorderSide(color: scheme.outlineVariant),
        textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        shape: _pill,
        textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        shape: const CircleBorder(),
        padding: const EdgeInsets.all(10),
      ),
    ),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: Colors.transparent,
      indicatorColor: scheme.primary.withValues(alpha: dark ? 0.22 : 0.12),
      indicatorShape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      selectedIconTheme: IconThemeData(color: scheme.primary),
      selectedLabelTextStyle: TextStyle(
        color: scheme.onSurface,
        fontWeight: FontWeight.w700,
        fontSize: 12,
      ),
      unselectedIconTheme: IconThemeData(color: scheme.onSurfaceVariant),
      unselectedLabelTextStyle: TextStyle(
        color: scheme.onSurfaceVariant,
        fontSize: 12,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 68,
      elevation: 0,
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      indicatorColor: scheme.primary.withValues(alpha: dark ? 0.22 : 0.12),
      indicatorShape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
      ),
      labelTextStyle: WidgetStatePropertyAll(
        TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: scheme.onSurface,
        ),
      ),
    ),
    tabBarTheme: TabBarThemeData(
      dividerColor: Colors.transparent,
      indicatorSize: TabBarIndicatorSize.label,
      indicator: BoxDecoration(
        color: scheme.primary.withValues(alpha: dark ? 0.22 : 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      labelColor: scheme.primary,
      unselectedLabelColor: scheme.onSurfaceVariant,
      labelStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
      unselectedLabelStyle: const TextStyle(
        fontWeight: FontWeight.w500,
        fontSize: 13,
      ),
    ),
    dividerTheme: DividerThemeData(
      color: scheme.outlineVariant.withValues(alpha: 0.5),
      space: 1,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: dark ? const Color(0xFF1B2240) : const Color(0xFF20263A),
      contentTextStyle: const TextStyle(
        color: Colors.white,
        fontWeight: FontWeight.w500,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
    listTileTheme: ListTileThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? Colors.white : null,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? scheme.primary
            : scheme.surfaceContainerHighest,
      ),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      side: BorderSide(color: scheme.outlineVariant),
      backgroundColor: dark
          ? Colors.white.withValues(alpha: 0.05)
          : Colors.white.withValues(alpha: 0.6),
      labelStyle: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: dark ? const Color(0xFF12172C) : const Color(0xFFFDFDFF),
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      titleTextStyle: text.titleLarge?.copyWith(fontWeight: FontWeight.w700),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: dark ? const Color(0xFF12172C) : const Color(0xFFFDFDFF),
      surfaceTintColor: Colors.transparent,
      modalBackgroundColor: dark
          ? const Color(0xFF12172C)
          : const Color(0xFFFDFDFF),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      showDragHandle: true,
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: dark ? const Color(0xFF151B33) : Colors.white,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: scheme.primary,
      linearTrackColor: scheme.surfaceContainerHighest,
    ),
  );
}
