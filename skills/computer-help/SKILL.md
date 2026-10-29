---
name: computer-help
description: Diagnose and repair a concrete problem on this computer (an app, setting, file, printer, sound, network or slowdown), keep a way to undo the change, and repeat the original task to show the fix worked.
---

Use this when someone says what they were trying to do and what went wrong. The job is
done when the thing they needed works again, not when a command succeeds.

1. **Confirm the computer.** Tools run where the Hermes gateway runs. Check the operating
   system, user and computer name with the terminal. If this is not the person's own
   computer (a remote or cloud gateway), say so plainly and stop; never present a
   different machine's state as theirs.
2. **Get the symptom in their words.** What were they doing, what happened instead, since
   when, and what changed recently. Ask one short question at a time, only when the
   answer changes what you do.
3. **Look before changing anything.** Reproduce the failure or inspect the real state:
   the app's own error, logs, devices, services, disk space, network, recent updates.
   - Windows: use PowerShell in the signed-in user's session (`Get-Printer`,
     `Get-PrintJob`, `Get-PnpDevice`, `Get-NetAdapter`, `Test-NetConnection`,
     `Get-WinEvent`, `Get-Volume`). Open a Settings page with `Start-Process ms-settings:<page>`.
     An administrator change shows a UAC prompt that the person must approve on screen;
     tell them first and never try to get around it.
   - macOS: use `system_profiler`, `lpstat`, `networksetup`, `scutil`, `log show`, `df`,
     `defaults read`. Privacy-protected access (Accessibility, Screen Recording, Full Disk
     Access, Automation) must be granted by the person in System Settings; open the exact
     pane for them and wait.
   - Use computer_use or the visible browser when the fix lives in a window rather than a
     command, and say what you are about to click.
4. **Choose the smallest fix and keep a way back.** Before changing a setting or file,
   save the old value or a timestamped copy and tell the person what you will change.
   Prefer per-user, reversible changes over system-wide ones. Do not delete personal
   files, turn off security software, run unknown scripts from the internet, or change
   accounts and passwords.
5. **Repeat the original task.** Print the page, play the sound, open the site, launch
   the app, sync the file. Check what software can check (the print job left the queue,
   the default audio device is right and unmuted, the page loads). Then ask the person to
   confirm what only they can see or hear: paper came out, sound is audible, the screen
   looks right. A process exit code is not proof that hardware works.
6. **Report.** Symptom, cause you found, exactly what changed (old to new), how to undo
   it, what you verified, what the person confirmed, and anything still unresolved.

If a step needs an administrator, a password, a restart, or a part you cannot reach,
stop at that point, keep what you learned, and say exactly what is needed. If the problem
is beyond what can be done safely here, suggest human help from BrainRoad
(support@brainroad.com) with a short summary the person can send, without passwords or
private file contents.
