// De-risk the N=64 patch:
//  (1) find EVERY function that calls a CommandSet method (get/set/clear/ctor/parse) and
//      report any +0x98 / +0x9c access in them -> catches a stray count/flag getter.
//  (2) for each getCommandButton caller, print the exact `CMP r32, 0x21` instruction
//      addresses (Phase-3 flip sites).
//@category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class CommandSetMVP extends GhidraScript {

    Set<Function> callersOf(long target) {
        Set<Function> fs = new LinkedHashSet<>();
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(toAddr(target));
        while (it.hasNext()) {
            Reference r = it.next();
            if (!r.getReferenceType().isCall()) continue;
            Function f = getFunctionContaining(r.getFromAddress());
            if (f != null) fs.add(f);
        }
        return fs;
    }

    @Override
    protected void run() throws Exception {
        long[] methods = {0x0080c837L /*get*/, 0x0080c8efL /*set*/, 0x0080c8e2L /*clear*/,
                          0x0080c91bL /*reset*/, 0x0080c949L /*ctor*/, 0x0080c9e1L /*parseBtn*/};
        Set<Function> cs = new LinkedHashSet<>();
        for (long m : methods) cs.addAll(callersOf(m));
        println("CommandSet-aware functions (callers of any method): " + cs.size());

        // (1) count/flag accesses in those functions
        println("\n==== +0x98 / +0x9c accesses inside CommandSet-aware functions ====");
        TreeSet<String> rows = new TreeSet<>();
        for (Function f : cs) {
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                String rep = ins.toString();
                if (rep.contains("0x98]") || rep.contains("0x9c]")) {
                    rows.add(String.format("  %s : %s   [%s]", ins.getAddress(), rep, f.getName()));
                }
            }
        }
        for (String r : rows) println(r);
        println("(known-good set is 8 sites: 0x80c8d2/8db/8ef/909/980/987 + 0x943df9 + 0x9a025e)");

        // (2) exact CMP r32,0x21 sites in getCommandButton callers
        println("\n==== CMP r32,0x21 sites in getCommandButton callers (Phase-3 flips) ====");
        TreeSet<String> cmps = new TreeSet<>();
        for (Function f : callersOf(0x0080c837L)) {
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                if (!ins.getMnemonicString().equalsIgnoreCase("CMP")) continue;
                for (int i = 0; i < ins.getNumOperands(); i++) {
                    Scalar s = ins.getScalar(i);
                    if (s != null && s.getUnsignedValue() == 0x21) {
                        byte[] b = ins.getBytes();
                        StringBuilder hx = new StringBuilder();
                        for (byte x : b) hx.append(String.format("%02x ", x));
                        cmps.add(String.format("  %s : %s | %s[%s]", ins.getAddress(), hx.toString().trim(), ins, f.getName()));
                    }
                }
            }
        }
        for (String c : cmps) println(c);
        println("count: " + cmps.size());
        println("\n=== DONE3 ===");
    }
}
