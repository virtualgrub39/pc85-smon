NAME MISC

PUBLIC EXIT
PUBLIC DELAY
PUBLIC EXEC

CSEG

EXIT:
    RST 0

DELAY:
DELAY_L:
    CALL DELAY_1MS
    dcr c
    jz DELAY_DONE
    jmp DELAY_L
DELAY_DONE:
    ret

DELAY_1MS: ; @ 2 MHz
    NOP         
    NOP         
    NOP        
    MVI A, 8Dh 
DELAY_MS_L:
    DCR A     
    JNZ DELAY_MS_L 
                
    RET   

EXEC:
    MOV H, B
    MOV L, C
    PCHL

END
