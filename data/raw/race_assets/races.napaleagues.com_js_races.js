/*!
 * NAPA Races v2.0.0 (http://www.naparaces.com)
 * Copyright 2015 NAPA
 */

    function functionMaster(Atext, Btext, form) {
        var A = parseFloat(Atext);
        var B = parseFloat(Btext);
        var d = document;
        var labA = d.getElementById('labelA');
        labA.innerHTML = "The race should be displayed here.";
        var labB = d.getElementById('labelB');
        labB.innerHTML = "The race should be displayed here.";
        var lab2 = d.getElementById('label2');
        lab2.innerHTML = "The difference should be displayed here.";
        var lab3 = d.getElementById('label3');
        lab3.innerHTML = "Difference: ";


        //0-39 Start
        if (parseFloat(Atext) - parseFloat(Btext) == 0 & (parseFloat(Atext) <= 39 )) {
            lab2.innerHTML = "0"
            labA.innerHTML = " 2";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) <= 39 & ((A - B) <= 19) )) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 2";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) <= 39 & ((A - B) >= 20))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 3";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) <= 39 & ((B - A) <= 19))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) <= 39 & ((B - A) >= 20))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 3";
        }
        //0-39 End

        //40-49 Start
        if (parseFloat(Atext) - parseFloat(Btext) == 0 & (parseFloat(Atext) >= 40) & (parseFloat(Atext) <= 49)) {
            lab2.innerHTML = "0"
            labA.innerHTML = " 3";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 40 & (parseFloat(Atext) <= 49) & ((A - B) <= 10))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 3";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 40 & (parseFloat(Atext) <= 49) & ((A - B) >= 11) & (A - B) <= 26)) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 3";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 40 & (parseFloat(Atext) <= 49) & ((A - B) >= 27))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 4";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 40 & (parseFloat(Btext) <= 49) & ((B - A) <= 10))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 40 & (parseFloat(Btext) <= 49) & ((B - A) >= 11) & (B - A) <= 26)) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 40 & (parseFloat(Btext) <= 49) & ((B - A) >= 27))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 4";
        }
        //40-49 End

        //50-69 Start
        if (parseFloat(Atext) - parseFloat(Btext) == 0 & (parseFloat(Atext) >= 50) & (parseFloat(Atext) <= 69)) {
            lab2.innerHTML = "0"
            labA.innerHTML = " 4";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 50 & (parseFloat(Atext) <= 69) & ((A - B) <=6 ) )) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 4";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 50 & (parseFloat(Atext) <= 69) & ((A - B) >= 7 & (A - B) <= 18 ))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 4";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 50 & (parseFloat(Atext) <= 69) & ((A - B) >= 19 & (A - B) <= 29))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 5";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 50 & (parseFloat(Atext) <= 69) & ((A - B) >= 30 & (A - B) <= 39))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 4";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 50 & (parseFloat(Atext) <= 69) & ((A - B) >= 40 & (A - B) <= 48))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 5";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 50 & (parseFloat(Atext) <= 69) & ((A - B) >= 49))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 2";
        }


        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 50 & (parseFloat(Btext) <= 69) & ((B - A) <= 6))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 4";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 50 & (parseFloat(Btext) <= 69) & ((B - A) >= 7 & (B - A) <= 18))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 50 & (parseFloat(Btext) <= 69) & ((B - A) >= 19 & (B - A) <= 29))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 50 & (parseFloat(Btext) <= 69) & ((B - A) >= 30 & (B - A) <= 39))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 50 & (parseFloat(Btext) <= 69) & ((B - A) >= 40 & (B - A) <= 48))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 50 & (parseFloat(Btext) <= 69) & ((B - A) >= 49))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 6";
        }
        //50-69 End




        //70-89 Start
        if (parseFloat(Atext) - parseFloat(Btext) == 0 & (parseFloat(Atext) >= 70) & (parseFloat(Atext) <= 89)) {
            lab2.innerHTML = "0"
            labA.innerHTML = " 5";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) <= 5))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 5";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 6 & (A - B) <= 14))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 5";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 15 & (A - B) <= 21))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 22 & (A - B) <= 28))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 5";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 29 & (A - B) <= 36))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 37 & (A - B) <= 46))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 7";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 47 & (A - B) <= 56))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 57 & (A - B) <= 62))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 7";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 70 & (parseFloat(Atext) <= 89) & ((A - B) >= 63))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 8";
			labB.innerHTML = " 2";
        }

        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) <= 5))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 5";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 6 & (B - A) <= 14))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 4";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 15 & (B - A) <= 21))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 4";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 22 & (B - A) <= 28))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 29 & (B - A) <= 36))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 37 & (B - A) <= 46))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 7";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 47 & (B - A) <= 56))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 57 & (B - A) <= 62))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 7";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 70 & (parseFloat(Btext) <= 89) & ((B - A) >= 63))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 8";
        }
        //70-89 End



        //90+ Start
        if (parseFloat(Atext) - parseFloat(Btext) == 0 & (parseFloat(Atext) >= 90)) {
            lab2.innerHTML = "0"
            labA.innerHTML = " 6";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) <= 4))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 5 & (A - B) <= 11))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 12 & (A - B) <= 17))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 7";
			labB.innerHTML = " 5";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 18 & (A - B) <= 22))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 6";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 23 & (A - B) <= 28))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 7";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 29 & (A - B) <= 35))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 8";
			labB.innerHTML = " 4";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 36 & (A - B) <= 42))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 7";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 43 & (A - B) <= 48))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 8";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 49 & (A - B) <= 58))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 9";
			labB.innerHTML = " 3";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 59 & (A - B) <= 68))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 8";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 69 & (A - B) <= 74))) {
            lab2.innerHTML = A - B;
            labA.innerHTML = " 9";
			labB.innerHTML = " 2";
        }
        if (parseFloat(Atext) > parseFloat(Btext) & (parseFloat(Atext) >= 90 & ((A - B) >= 75 ))){
            lab2.innerHTML = A - B;
            labA.innerHTML = " 10";
			labB.innerHTML = " 2";
        }


        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) <= 4))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 6";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 5 & (B - A) <= 11))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 5";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 12 & (B - A) <= 17))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 5";
			labB.innerHTML = " 7";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 18 & (B - A) <= 22))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 4";
			labB.innerHTML = " 6";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 23 & (B - A) <= 28))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 4";
			labB.innerHTML = " 7";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 29 & (B - A) <= 35))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 4";
			labB.innerHTML = " 8";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 36 & (B - A) <= 42))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 7";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 43 & (B - A) <= 48))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 8";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 49 & (B - A) <= 58))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 3";
			labB.innerHTML = " 9";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 59 & (B - A) <= 68))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 8";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 69 & (B - A) <= 74))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 9";
        }
        if (parseFloat(Btext) > parseFloat(Atext) & (parseFloat(Btext) >= 90 & ((B - A) >= 75))) {
            lab2.innerHTML = B - A;
            labA.innerHTML = " 2";
			labB.innerHTML = " 10";
        }


        //90+ End



    }

    function ClearForm(form) {
        var d = document;
        var labA = d.getElementById('labelA');
        labA.innerHTML = "";
        var labB = d.getElementById('labelB');
        labB.innerHTML = "";
        var lab20 = d.getElementById('label2');
        lab20.innerHTML = "";
        var lab30 = d.getElementById('label3');
        lab30.innerHTML = "";
        var lab1 = d.getElementById('label1');
        var lab2 = d.getElementById('label2');
        var lab3 = d.getElementById('label3');
        form.input_A.value = "";
        form.input_B.value = "";
        lab1.innerHTML = "";
        lab2.innerHTML = "";
        lab3.innerHTML = "";
		document.forms['Calculator'].elements['input_A'].focus();
    }

    // end of JavaScript functions -->