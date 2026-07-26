// Classify getCommandButton / setCommandButton call sites: does the containing function
// bound its slot loop on the literal 33 (cmp r,0x21) or on the count field ([cs+0x98])?
//@category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class CommandSetCallers extends GhidraScript {
    DecompInterface dec;

    boolean funcHasCmp33(Function f) {
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            if (ins.getMnemonicString().toUpperCase().startsWith("CMP")) {
                for (int i = 0; i < ins.getNumOperands(); i++) {
                    Scalar s = ins.getScalar(i);
                    if (s != null && s.getUnsignedValue() == 0x21) return true;
                }
            }
        }
        return false;
    }

    boolean funcReadsCountField(Function f) {
        // look for any operand referencing displacement 0x98 (m_commandCount)
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            String rep = ins.toString();
            if (rep.contains("0x98]")) return true;
        }
        return false;
    }

    void classifyCallers(long target, String label) {
        println("\n================ callers of " + label + " (0x" + Long.toHexString(target) + ") ================");
        Address a = toAddr(target);
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(a);
        // group by containing function
        TreeMap<Long, int[]> perFunc = new TreeMap<>();      // funcEntry -> [callCount]
        TreeMap<Long, String> funcName = new TreeMap<>();
        TreeMap<Long, Boolean> hasLit = new TreeMap<>();
        TreeMap<Long, Boolean> hasCnt = new TreeMap<>();
        int total = 0;
        while (it.hasNext()) {
            Reference ref = it.next();
            if (!ref.getReferenceType().isCall()) continue;
            total++;
            Function f = getFunctionContaining(ref.getFromAddress());
            if (f == null) continue;
            long fe = f.getEntryPoint().getOffset();
            perFunc.computeIfAbsent(fe, k -> new int[]{0})[0]++;
            if (!funcName.containsKey(fe)) {
                funcName.put(fe, f.getName());
                hasLit.put(fe, funcHasCmp33(f));
                hasCnt.put(fe, funcReadsCountField(f));
            }
        }
        println("total call refs: " + total + " ; distinct functions: " + perFunc.size());
        println(String.format("%-12s %-5s %-9s %-9s %s", "func", "calls", "cmp0x21", "reads98", "bound"));
        int lit=0, cnt=0, other=0;
        for (Long fe : perFunc.keySet()) {
            boolean L = hasLit.get(fe), C = hasCnt.get(fe);
            String bound = L ? "LITERAL_33" : (C ? "count(+0x98)" : "indexed/other");
            if (L) lit++; else if (C) cnt++; else other++;
            println(String.format("0x%08x  %-5d %-9s %-9s %s", fe, perFunc.get(fe)[0], L, C, bound + "  " + funcName.get(fe)));
        }
        println("SUMMARY " + label + ": functions bounding on LITERAL_33=" + lit + ", count-field=" + cnt + ", indexed/other=" + other);
    }

    void decomp(long va, String label) {
        Function f = getFunctionContaining(toAddr(va));
        println("\n---- " + label + " @0x" + Long.toHexString(va) + " ----");
        if (f == null) { println("<no func>"); return; }
        DecompileResults r = dec.decompileFunction(f, 45, monitor);
        if (r != null && r.decompileCompleted()) println(r.getDecompiledFunction().getC());
    }

    @Override
    protected void run() throws Exception {
        dec = new DecompInterface();
        dec.openProgram(currentProgram);
        decomp(0x0080c837L, "getCommandButton");
        decomp(0x0080c8efL, "setCommandButton");
        classifyCallers(0x0080c837L, "getCommandButton");
        classifyCallers(0x0080c8efL, "setCommandButton");
        dec.dispose();
        println("\n=== DONE2 ===");
    }
}
