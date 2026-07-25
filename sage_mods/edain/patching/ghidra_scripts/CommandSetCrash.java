//@category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class CommandSetCrash extends GhidraScript {
    DecompInterface dec;
    void dc(long va) throws Exception {
        Address a = toAddr(va);
        Function f = getFunctionContaining(a);
        println("\n================ containing 0x" + Long.toHexString(va) + " -> " + (f==null?"?":f.getName()+" @"+f.getEntryPoint()) + " ================");
        if (f == null) return;
        // stack frame size
        println("frame size = 0x" + Integer.toHexString(f.getStackFrame().getFrameSize()));
        DecompileResults r = dec.decompileFunction(f, 60, monitor);
        if (r != null && r.decompileCompleted()) println(r.getDecompiledFunction().getC());
        else println("<decompile failed>");
    }
    protected void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        long[] addrs = {0x00944534L, 0x009448aeL, 0x0071fd8eL, 0x0071ef93L, 0x0071dcddL,
                        0x00720302L, 0x00809ffbL, 0x00715599L};
        for (long a : addrs) dc(a);
        dec.dispose();
        println("\n=== DONE4 ===");
    }
}
