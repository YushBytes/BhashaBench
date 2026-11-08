"""The end-to-end voice testing pipeline (Phase 7).

Connects the Phase 6 caller, Timbre synthesis, audio degradation, a bot
adapter and Prisma transcription into one multi-turn run. Every module here
reuses the existing subsystems rather than reimplementing them.
"""
