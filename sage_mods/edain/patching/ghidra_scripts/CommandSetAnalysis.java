// Ghidra headless post-script: decompile CommandSet-related functions and dump xrefs.
//@category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.util.*;

public class CommandSetAnalysis extends GhidraScript {
    DecompInterface dec;

    void decompAt(long va, String label) throws Exception {
        Address a = toAddr(va);
        Function f = getFunctionContaining(a);
        println("\n================ " + label + "  (va=0x" + Long.toHexString(va) + ") ================");
        if (f == null) { println("  <no function at addr>"); return; }
        println("  function: " + f.getName() + " @ " + f.getEntryPoint());
        DecompileResults r = dec.decompileFunction(f, 60, monitor);
        if (r != null && r.decompileCompleted()) {
            println(r.getDecompiledFunction().getC());
        } else {
            println("  <decompile failed: " + (r==null?"null":r.getErrorMessage()) + ">");
        }
    }

    void xrefs(long va, String label) {
        Address a = toAddr(va);
        println("\n---- xrefs to " + label + " (0x" + Long.toHexString(va) + ") ----");
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(a);
        while (it.hasNext()) {
            Reference ref = it.next();
            Address from = ref.getFromAddress();
            Function f = getFunctionContaining(from);
            println("  from " + from + "  (" + ref.getReferenceType() + ")  in " + (f==null?"?":f.getName()));
        }
    }

    @Override
    protected void run() throws Exception {
        dec = new DecompInterface();
        dec.openProgram(currentProgram);

        // Field-parse table and its consumers
        xrefs(0x00c4f3d8L, "CommandSet field-parse table");
        // constructor, alloc/create, block parser, parseCommandButton, initFromINI
        decompAt(0x0080c949L, "CommandSet constructor");
        decompAt(0x0072028bL, "CommandSet create/alloc (operator new 0xA0)");
        decompAt(0x007205d0L, "parseCommandSetDefinition (calls initFromINI)");
        decompAt(0x0080c9e1L, "parseCommandButton (stores m_command[i])");

        // Find functions that reference the CommandSet store global 0xde7744 (TheCommandSetStore)
        xrefs(0x00de7744L, "TheCommandSetStore global");
        dec.dispose();
        println("\n=== DONE ===");
    }
}
