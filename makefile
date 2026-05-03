ifeq ($(OS),Windows_NT)
    BINEXT := .exe
else
    BINEXT :=
endif

ASM    = ./bin/asm80$(BINEXT)
PLMC   = ./bin/plm80c$(BINEXT)
LN     = ./bin/link$(BINEXT)
LOCATE = ./bin/locate$(BINEXT)
OBJHEX = ./bin/objhex$(BINEXT)
EEPROG = python ./bin/rreaper.py

SOURCE_DIR = src
ASM_DIR = asm
LIB_DIR = lib
OBJ_DIR = obj
OUT_DIR = out

empty :=
space := $(empty) $(empty)
comma := ,

LIBS = $(LIB_DIR)/plm80.lib

# ==========================================
#             BUILD TARGETS
# ==========================================
all: $(OUT_DIR)/monitor.hex

$(OBJ_DIR) $(OUT_DIR):
	mkdir -p $@

$(OBJ_DIR)/%.plm.obj: $(SOURCE_DIR)/%.plm | $(OBJ_DIR)
	$(PLMC) $< 'OBJECT($@)' 'PRINT($(OBJ_DIR)/$*.plm.lst)'

$(OBJ_DIR)/%.asm.obj: $(ASM_DIR)/%.asm | $(OBJ_DIR)
	$(ASM) $< 'OBJECT($@)' 'PRINT($(OBJ_DIR)/$*.asm.lst)'

# ==========================================
#          MONITOR, API & TOOLS 
# ==========================================

COM = COM7

API_SRC_PLM += $(SOURCE_DIR)/main.plm 

API_SRC_PLM += $(SOURCE_DIR)/char.plm 
API_SRC_PLM += $(SOURCE_DIR)/conio.plm
API_SRC_PLM += $(SOURCE_DIR)/memory.plm

API_SRC_ASM += $(SOURCE_DIR)/conio.asm 
API_SRC_ASM += $(SOURCE_DIR)/misc.asm

API_OBJS = $(patsubst $(SOURCE_DIR)/%.plm, $(OBJ_DIR)/%.plm.obj, $(API_SRC_PLM)) \
		   $(patsubst $(SOURCE_DIR)/%.asm, $(OBJ_DIR)/%.asm.obj, $(API_SRC_ASM))

$(OBJ_DIR)/bios.obj: $(ASM_DIR)/bios.asm | $(OBJ_DIR)
	$(ASM) $< 'OBJECT($@)' 'PRINT($(OBJ_DIR)/bios.lst)'

$(OBJ_DIR)/monitor.obj: $(OBJ_DIR)/bios.obj $(API_OBJS) $(LIBS) | $(OBJ_DIR)
	$(LN) $(subst $(space),$(comma),$(strip $^)) TO $@

$(OBJ_DIR)/monitor.abs: $(OBJ_DIR)/monitor.obj
	$(LOCATE) $< TO $@ 'CODE(0200H)' 'DATA(3E00H)' 'STACK(3FFFH)'

$(OUT_DIR)/monitor.hex: $(OBJ_DIR)/monitor.abs | $(OUT_DIR)
	$(OBJHEX) $< TO $@

write: $(OUT_DIR)/monitor.hex
	$(EEPROG) $(COM) --baud 19200 write 0 --hex $<

verify: $(OUT_DIR)/monitor.hex
	$(EEPROG) $(COM) --baud 19200 verify 0 --hex $<

clean:
	$(RM) -r $(OBJ_DIR) $(OUT_DIR)
	$(RM) *.hex *.obj *.abs *.lst *.map

.PHONY: write verify all clean
