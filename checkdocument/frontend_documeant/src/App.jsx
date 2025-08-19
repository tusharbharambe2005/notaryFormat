// src/App.js
import Select from 'react-select';
import React, { useState } from 'react';
import './App.css'; // if you use external CSS

function App() {
  const [frontImage1, setfrontImage1] = useState(null);
  const [backImage1, setbackImage1] = useState(null);
  const [frontImage2, setfrontImage2] = useState(null);
  const [backImage2, setbackImage2] = useState(null);
  const [selected, setSelected] = useState('');

  const options = [
    { value: 'PANCARD', label: 'PAN CARD' },
    { value: 'Driving License', label: 'Driving License' },
    { value: 'Residence Permit', label: 'Residence Permit' },
    { value: 'Foreign Passport', label: 'Foreign Passport' },

  ];

  const handleSubmit = async (layoutType) => {
    if (!frontImage1) {
      alert("Please upload the front image.");
      return;
    }

    const formData = new FormData();
    formData.append("front_image", frontImage1);
    if (backImage1) {
      formData.append("back_image", backImage1);
    }
    if(frontImage2){
      formData.append("front_image2",frontImage2)
    }
    if (backImage2){
      formData.append("back_image2",backImage2)
    }

    formData.append("layout", layoutType);
  
    formData.append('document_type',selected);

    try {
      const response = await fetch("http://localhost:8000/api/generate-pdf/", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error("PDF generation failed");
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "card_document.pdf");
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
    } catch (error) {
      console.error("Error generating PDF:", error);
      alert("Something went wrong while generating the PDF.");
    }
  };

  return (
    <div style={styles.page}>
      <div style={styles.container} className="fade-in">
        <div style={styles.logoSection}>
          <img
            src="https://cdn-icons-png.flaticon.com/512/337/337946.png"
            alt="PDF Logo"
            style={styles.logo}
            className="spin"
          />
          <h1 style={styles.heading}>Smart PDF Generator</h1>
        </div>

        <form>
          <div style={styles.field}>
            <label style={styles.label}>Front Image (required):</label>
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setfrontImage1(e.target.files[0])}
              style={styles.input}
              required
            />
            {frontImage1 && <p style={styles.filename}>📎 {frontImage1.name}</p>}
          </div>

          <div style={styles.field}>
            <label style={styles.label}>Back Image (optional):</label>
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setbackImage1(e.target.files[0])}
              style={styles.input}
            />
            {backImage1 && <p style={styles.filename}>📎 {backImage1.name}</p>}
          </div>
          <div style={styles.field}>
            <label style={styles.label}>Front Image 2(optional):</label>
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setfrontImage2(e.target.files[0])}
              style={styles.input}
            />
            {frontImage2 && <p style={styles.filename}>📎 {frontImage2.name}</p>}
          </div>

          <div style={styles.field}>
            <label style={styles.label}>Back Image 2(optional):</label>
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setbackImage2(e.target.files[0])}
              style={styles.input}
            />
            {backImage2 && <p style={styles.filename}>📎 {backImage2.name}</p>}
          </div>
          <div style={styles.field}>
            <label>Select your card</label>
            <select value={selected} onChange={(e) => setSelected(e.target.value)}>
              <option value="">-- Select One --</option>
              {options.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

          </div>

          <div style={styles.buttonGroup}>
            <button
              type="button"
              onClick={() => handleSubmit("normal")}
              style={{ ...styles.button, backgroundColor: "#4CAF50" }}
              className="button-glow"
            >
              Generate Normal PDF
            </button>
            <button
              type="button"
              onClick={() => handleSubmit("us")}
              style={{ ...styles.button, backgroundColor: "#008CBA" }}
              className="button-glow"
            >
              🇺🇸 Generate US PDF
            </button>
            <button
              type="button"
              onClick={() => handleSubmit("uk")}
              style={{ ...styles.button, backgroundColor: "#008CCD" }}
              className="button-glow"
            >
              Generate UK PDF
             </button> 
            
          </div>

        </form>
      </div>
    </div>
  );
}

// 🎨 Inline CSS
const styles = {
  page: {
    backgroundColor: "#f4f7fa",
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "20px",
  },
  container: {
    backgroundColor: "#ffffff",
    padding: "35px 30px",
    borderRadius: "18px",
    boxShadow: "0 10px 25px rgba(0, 0, 0, 0.15)",
    width: "100%",
    maxWidth: "520px",
    transition: "transform 0.3s ease-in-out",
  },
  logoSection: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: "25px",
    flexDirection: "column",
  },
  logo: {
    width: "70px",
    height: "70px",
    marginBottom: "10px",
  },
  heading: {
    fontSize: "24px",
    fontWeight: "bold",
    color: "#222",
    fontFamily: "'Segoe UI', sans-serif",
  },
  field: {
    marginBottom: "20px",
  },
  label: {
    display: "block",
    marginBottom: "8px",
    fontWeight: "600",
    color: "#444",
  },
  input: {
    padding: "10px 14px",
    borderRadius: "8px",
    border: "1px solid #ccc",
    width: "100%",
    fontSize: "15px",
  },
  filename: {
    marginTop: "8px",
    fontSize: "14px",
    color: "#666",
    fontStyle: "italic",
  },
  buttonGroup: {
    display: "flex",
    flexDirection: "column",
    gap: "14px",
    marginTop: "10px",
  },
  button: {
    padding: "14px",
    fontSize: "16px",
    borderRadius: "10px",
    border: "none",
    color: "#fff",
    cursor: "pointer",
    fontWeight: "600",
    transition: "all 0.3s ease",
  },
};

export default App;
