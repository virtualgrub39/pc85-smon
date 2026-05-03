/* Soft-resets system. Returns to serial monitor. */
EXIT: PROCEDURE EXTERNAL;
END EXIT;

/* Does nothing for MS miliseconds.  */
DELAY: PROCEDURE(MS) EXTERNAL;
    DECLARE MS BYTE;
END DELAY;

