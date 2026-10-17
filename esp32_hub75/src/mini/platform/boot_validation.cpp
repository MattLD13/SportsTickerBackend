// Keep rollback pending until FirmwareUpdater validates the running display.
extern "C" bool verifyRollbackLater() { return true; }
