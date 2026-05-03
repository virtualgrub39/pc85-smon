NAME CONIO

PUBLIC CONOUT
PUBLIC CONIN
PUBLIC CONSTAT
PUBLIC CONINIT

IO0         EQU 00H
UART_DATA   EQU IO0 OR 0H
UART_CTRL   EQU IO0 OR 1H

CSEG

CONINIT:
    ; Reset
    XRA A
    OUT UART_CTRL
    OUT UART_CTRL
    OUT UART_CTRL
    MVI A, 40H
    OUT UART_CTRL

    ; Mode: 1 stop, no parity, 8-bit character, 16x baud
    MVI A, 01001110B
    OUT UART_CTRL

    ; Command: error reset, RTS, RX enable, TX enable
    MVI A, 00010101B
    OUT UART_CTRL
    
    RET

CONOUT:
    push psw            
CO_WAIT:
    in UART_CTRL
    ani 01h               ; TXRDY
    jz CO_WAIT
    mov a, c            
    out UART_DATA
    pop psw              
    ret

CONIN:
CI_WAIT:
    in UART_CTRL
    ani 02h               ; RXRDY
    jz CI_WAIT
    in UART_DATA
    ret

CONSTAT:
    in UART_CTRL
    ani 02h         ; Check RXRDY bit
    jz CS_EMPTY
    mvi a, 0FFh
    ret
CS_EMPTY:
    xra a           ; A = 0
    ret

END
