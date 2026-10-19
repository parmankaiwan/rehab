import{fireEvent,render,screen,waitFor}from"@testing-library/react";
import{beforeEach,describe,expect,it,vi}from"vitest";
import{EmgComparisonDashboard}from"./EmgComparisonDashboard";

const catalog={hardware_limit:"Real spatial GQ requires 3 channels; current board has 1 channel.",functions:["CENTRAL_PEAK","LINEAR"],models:[{id:"LOGISTIC_REGRESSION",name:"LOGISTIC REGRESSION",category:"Classical baseline",input_representation:"Tabular",estimated_cost:"LOW",advantage:"Interpretable",eligible:true},{id:"CNN_1D",name:"CNN 1D",category:"Deep learning",input_representation:"Sequence",estimated_cost:"MEDIUM",advantage:"Patterns",eligible:true}]};
const simulation={time:[0,1],mean_curve:[.4,.5],gq_curve:[.45,.55],reference_curve:[.46,.54],methods:{ARITHMETIC_MEAN:{rmse:.05},GAUSSIAN_QUADRATURE:{rmse:.01}},comparison:{winner:"GAUSSIAN_QUADRATURE",gq_rmse_improvement_percent:80}};

beforeEach(()=>vi.stubGlobal("fetch",vi.fn(async(input:string|URL|Request,init?:RequestInit)=>{const url=String(input);if(url.endsWith("/catalog"))return new Response(JSON.stringify(catalog));if(url.endsWith("/simulation")&&init?.method==="POST")return new Response(JSON.stringify(simulation));return new Response(JSON.stringify({detail:"unexpected"}),{status:400})})));

describe("EMG comparison dashboard",()=>{it("shows hardware limits, equations, selectable deep models, and measured simulation metrics",async()=>{render(<EmgComparisonDashboard/>);expect(await screen.findByText(/current board has 1 channel/i)).toBeInTheDocument();expect(screen.getByText(/5A\/18/)).toBeInTheDocument();expect(screen.getByRole("button",{name:/CNN 1D/i})).toBeEnabled();fireEvent.click(screen.getByRole("button",{name:/run simulation/i}));await waitFor(()=>expect(screen.getByText("0.01000")).toBeInTheDocument());expect(screen.getAllByText("GAUSSIAN QUADRATURE").length).toBeGreaterThan(0)})});
