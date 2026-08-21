#include <limits.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

/*
 * The visible DMG app is a tiny native launcher. Finder reliably foregrounds
 * this AppKit process; it then replaces itself with the AppleScriptObjC core
 * so the existing installer UI and restart-safe engine remain unchanged.
 */
int main(void) {
    char executable[PATH_MAX];
    uint32_t executableSize = sizeof(executable);
    if (_NSGetExecutablePath(executable, &executableSize) != 0) return 1;

    char resolved[PATH_MAX];
    if (!realpath(executable, resolved)) return 1;

    char *contents = strstr(resolved, "/Contents/MacOS/");
    if (!contents) return 1;
    *contents = '\0';

    char corePath[PATH_MAX];
    int written = snprintf(corePath, sizeof(corePath),
                           "%s/Contents/Resources/AdmiraCore.app/Contents/MacOS/applet",
                           resolved);
    if (written <= 0 || (size_t)written >= sizeof(corePath)) return 1;

    char *const childArguments[] = { corePath, NULL };
    pid_t childPid = 0;
    if (posix_spawn(&childPid, corePath, NULL, NULL, childArguments, environ) != 0) return 1;
    return 0;
}
