import config from "../../config/rehab_modules.json";

export type PatientModule={id:string;slug:string;patient_display_name:string;patient_description:string;patient_icon:string;requires_cv:boolean;requires_emg:boolean;optional_emg:boolean};

export function patientModules():PatientModule[]{
  return config.modules.filter((module)=>module.patient_enabled) as PatientModule[];
}
