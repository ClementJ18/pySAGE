/*
 * sage_accel - declarations shared between the module's source files.
 *
 * Derived, with his permission, from OH1A's bfme2_accel.dll.
 */

#ifndef SAGE_ACCEL_H
#define SAGE_ACCEL_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <d3d9.h>

/* The thread that armed the module and created the device: the one a render thread would take
 * work from. Set once, before any hook that reads it is installed. */
extern DWORD g_game_thread;

void log_line(const char *fmt, ...);

/* census.c - milestone M1: count every device, effect and lock call, and report every 30 s. */
void census_arm(void);
void census_hook_direct3d(IDirect3D9 *d3d);

#endif
