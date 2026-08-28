import { Check, CircleAlert, HelpCircle, X } from "lucide-react";
import { PostureState } from "@/types/posture";
export function StateIcon({ state, size=18 }: { state: PostureState; size?: number }) { const props={size,"aria-hidden":true}; return state === "GREEN" ? <Check {...props}/> : state === "ORANGE" ? <CircleAlert {...props}/> : state === "RED" ? <X {...props}/> : <HelpCircle {...props}/>; }
