import Header from "./components/Header";
import SMAPTimeSeries from "./components/SMAPTimeSeries";
import CanopyCoverBar from "./components/CanopyCoverBar";
import SMAPAnnualMeans from "./components/SMAPAnnualMeans";
import SMAPAnnualMeansAllCounties from "./components/SMAPAnnMeansAllCounty";
import TreeInventorySecrtion from "./components/TreeInventorySection";
import Footer from "./components/Footer";

export default function App() {
  return (
    <div style={{ fontFamily: "Inter, sans-serif", minHeight: "100vh",
                  display: "flex", flexDirection: "column" }}>
      <Header />
      <main style={{ flex: 1, background: "#fff" }}>
        <CanopyCoverBar />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SMAPTimeSeries />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SMAPAnnualMeans />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SMAPAnnualMeansAllCounties />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <TreeInventorySecrtion />
      </main>
      <Footer />
    </div>
  );
}