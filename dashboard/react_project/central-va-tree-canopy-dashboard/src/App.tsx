import Header from "./components/Header";
import SMAPTimeSeries from "./components/SMAPTimeSeries";
//import CanopyCoverBar from "./components/CanopyCoverBar";
import SMAPAnnualMeans from "./components/SMAPAnnualMeans";
import SMAPAnnualMeansAllCounties from "./components/SMAPAnnMeansAllCounty";
import TreeInventorySection from "./components/TreeInventorySection";
//import TreeCanopyChart from "./components/TreeCanopyChart";
import SplitPanelDashboard from "./components/SplitPanelDashboard";
import AoiTimeSeriesPanel  from "./components/AoiTimeSeriesPanel";
import PolicyPanel from "./components/PolicyPanel";
import LidarCanopyPanel from "./components/LidarCanopyPanel";
import Footer from "./components/Footer";

export default function App() {
  return (
    <div style={{ fontFamily: "Inter, sans-serif", minHeight: "100vh",
                  display: "flex", flexDirection: "column" }}>
      <Header />
      <main style={{ flex: 1, background: "#fff" }}>
        {/* <CanopyCoverBar />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <TreeCanopyChart />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} /> */}
        <LidarCanopyPanel />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} /> 
        <SMAPTimeSeries />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SMAPAnnualMeans />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SMAPAnnualMeansAllCounties />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SplitPanelDashboard />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <AoiTimeSeriesPanel />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <PolicyPanel />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <TreeInventorySection />
      </main>
      <Footer />
    </div>
  );
}