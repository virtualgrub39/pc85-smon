NAME BIOS

EXTRN MONITOR_MAIN

ROMSTART    EQU 0000H
RAMSTART    EQU 2000H
OSRAMSTART  EQU 3D00H   ; Grows up. Can be used for any memory needs by the BIOS. Should not ever be touched by user applications.
RAMEND      EQU 3FFFH

; RST JUMP TABLE

    ORG 000H
RST0:
    JMP START
    ORG 008H
RST1:
    ORG 010H
RST2:
    ORG 018H
RST3:
    ORG 020H
RST4:
    ORG 025H
TRAP:
    ORG 028H
RST5:
    ORG 02CH
RST55:
    ORG 030H
RST6:
    ORG 034H
RST65:
    ORG 038H
RST7:
    JMP CRASH

; SYSTEM API TABLE

SYSFN MACRO FNAME
    EXTRN FNAME
    JMP FNAME
ENDM

    ORG 0100H
$INCLUDE (inc/api.asm)

; CODE
START:
    LXI SP, RAMEND + 1

    LXI H, OSRAMSTART
    XRA A
CLEAR_RAM:
    MOV M, A
    INX H
    MOV A, H
    CPI HIGH RAMEND
    JNZ CLEAR_RAM

    CALL MONITOR_MAIN

    RST 0

CRASH:
    DI                 

    SHLD SAVE_HL      
    
    PUSH PSW
    POP H
    SHLD SAVE_AF        
    
    MOV H, B
    MOV L, C
    SHLD SAVE_BC      
    
    XCHG            
    SHLD SAVE_DE        

    POP H               
    SHLD SAVE_PC        

    LXI B, CRASH_MSG
    CALL PRINTLN

    LXI B, CRASH_MSG_PC
    CALL PRINT
    LHLD SAVE_PC
    MOV B, H           
    MOV C, L
    CALL PRINT_HEX16
    CALL PRINT_CRLF

    ; Print A
    LXI B, CRASH_MSG_A
    CALL PRINT
    LDA SAVE_AF + 1     
    MOV C, A         
    CALL PRINT_HEX8
    CALL PRINT_CRLF

    ; Print B
    LXI B, CRASH_MSG_B
    CALL PRINT
    LDA SAVE_BC + 1 
    MOV C, A
    CALL PRINT_HEX8
    CALL PRINT_CRLF

    ; Print C
    LXI B, CRASH_MSG_C
    CALL PRINT
    LDA SAVE_BC         
    MOV C, A
    CALL PRINT_HEX8
    CALL PRINT_CRLF

    ; Print D
    LXI B, CRASH_MSG_D
    CALL PRINT
    LDA SAVE_DE + 1    
    MOV C, A
    CALL PRINT_HEX8
    CALL PRINT_CRLF

    ; Print E
    LXI B, CRASH_MSG_E
    CALL PRINT
    LDA SAVE_DE         
    MOV C, A
    CALL PRINT_HEX8
    CALL PRINT_CRLF

    ; Print HL
    LXI B, CRASH_MSG_HL
    CALL PRINT
    LHLD SAVE_HL
    MOV B, H
    MOV C, L
    CALL PRINT_HEX16
    CALL PRINT_CRLF

    RST 0

DSEG
SAVE_AF: DS 2
SAVE_BC: DS 2
SAVE_DE: DS 2
SAVE_HL: DS 2
SAVE_PC: DS 2

CSEG
CRASH_MSG:    DB 13,10,'*** SYSTEM PANIC ***',0
CRASH_MSG_PC: DB 'AT PC = ',0
CRASH_MSG_A:  DB '    A = ',0
CRASH_MSG_B:  DB '    B = ',0
CRASH_MSG_C:  DB '    C = ',0
CRASH_MSG_D:  DB '    D = ',0
CRASH_MSG_E:  DB '    E = ',0
CRASH_MSG_HL: DB '   HL = ',0

END
